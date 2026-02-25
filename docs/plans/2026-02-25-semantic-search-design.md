# Semantic Search for code-memory

## Problem

`recall` uses SQL LIKE for search. This fails for any query that doesn't exactly match stored text. "Product Origin relation" misses memories stored about "Origin and Product association." Even rephrasing the same question ("Origin Product relation") returns nothing. The symbol index (`query_symbols`) has the same problem — exact substring matching only.

Result: recall is useless for natural-language queries, and nobody bothers calling `remember` because they can't get value back out.

## Solution

Replace keyword matching with vector similarity search using a local ONNX embedding model. Add a unified `search` tool that queries across memories and symbols simultaneously, with automatic relationship detection from the dependency graph.

## Constraints

- Offline, no API keys required
- Lightweight — no 500MB model downloads
- Unified search across memories, symbols, and dependencies

## Architecture

### New component: `EmbeddingEngine`

A module (`src/code_memory/embedding_engine.py`) that handles:
- Loading the ONNX model (`all-MiniLM-L6-v2` int8 quantized, ~23MB)
- Tokenizing text (HuggingFace `tokenizers` library)
- Computing 384-dimensional embeddings
- Cosine similarity computation via numpy

Singleton pattern, lazy-loaded on first use (same as `_manager` and `_graph` today).

### New MCP tool: `search(query, top_k=10)`

Unified semantic search that:
1. Embeds the query
2. Computes cosine similarity against all stored embeddings (memories + symbols)
3. Returns ranked results across both, with source type labels
4. Detects relationships between top-scoring symbols via the dependency graph

### Database changes

New table:
```sql
CREATE TABLE embeddings (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    source_type TEXT NOT NULL,  -- 'memory' or 'symbol'
    source_id INTEGER NOT NULL, -- FK to memories.id or symbols.id
    text TEXT NOT NULL,          -- the text that was embedded
    vector BLOB NOT NULL,        -- 384-dim float32 as bytes
    UNIQUE(project_id, source_type, source_id)
);
```

### Changes to existing tools

- `remember()` — auto-computes and stores an embedding alongside the memory
- `index_project()` — batch-embeds all new/changed symbols after indexing
- `recall(query)` — becomes a thin wrapper around `search` filtered to `source_type='memory'`
- `query_symbols(name)` — becomes a thin wrapper around `search` filtered to `source_type='symbol'`
- `forget()` — deletes the corresponding embedding row

Both `recall` and `query_symbols` are kept for backward compatibility, but `search` is the primary tool.

## Embedding Text Strategy

What text gets embedded for each source type:

**Memories:**
`"{notes} {symbol_name} {file_path}"` — concatenate all fields so searching by any dimension works.
Example: `"Validates JWT against Redis UserService.login src/auth.py"`

**Symbols:**
`"{symbol_name} {symbol_type} {signature} {file_path}"`
Example: `"Product class class Product(Base) src/models/product.py"`

**Dependencies (edges):**
Not embedded separately. The `search` tool detects relationships by checking the dependency graph for edges between top-scoring symbols.

**Re-embedding triggers:**
- `remember()` — embed immediately
- `index_project()` — batch-embed all new/changed symbols
- `forget()` — delete the corresponding embedding row

## Search UX

Example output for `search("Product Origin")`:

```
Results for "Product Origin":

1. [symbol] class Product in src/models/product.py:15-45
   class Product(Base)
2. [symbol] class Origin in src/models/origin.py:8-30
   class Origin(Base)
3. [relationship] Product -> Origin via:
   - Product.origin_id (FK dependency)
   - get_dependencies shows: Product imports Origin
4. [memory] #12 in src/models/product.py (Product): "Product belongs to Origin via origin_id foreign key"
```

**Relationship detection logic:**
After retrieving top-k results by cosine similarity, check if 2+ symbols appear. For each pair, query the dependency graph for edges. If edges exist, insert a `[relationship]` entry.

## Model Download & Lifecycle

**First-run:**
On first call to any tool needing embeddings, check for the model at `~/.code-memory/models/all-MiniLM-L6-v2-int8/`. If missing, download from HuggingFace Hub (~23MB) using `huggingface_hub.snapshot_download`.

**Lazy loading:**
ONNX session created once on first embedding call, cached as module singleton.

**Fallback:**
If model unavailable (no internet, download fails), fall back to SQL LIKE search with a warning. Next session retries.

## Dependencies

| Package | Size | Purpose |
|---------|------|---------|
| `onnxruntime` | ~15MB wheel | Model inference |
| `tokenizers` | ~7MB wheel | Fast tokenization |
| `huggingface_hub` | ~2MB wheel | Model download |
| Model file | ~23MB (one-time) | `all-MiniLM-L6-v2` int8 |

## Error Handling

- **No internet on first run** — graceful fallback to SQL LIKE, log warning, retry next session
- **Corrupt model file** — delete and re-download on next call
- **Embedding dimension mismatch** (model updated) — detect via stored vector size, re-embed all
- **Empty index** — return "No indexed content. Run `index_project` first."

## Performance

- Single query embedding: ~5ms on CPU
- Batch-embed 1000 symbols: ~2-3 seconds
- Cosine similarity over 10k vectors (numpy): <10ms
- No vector DB needed — SQLite + numpy is sufficient for project-sized corpora

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/code_memory/embedding_engine.py` | **New** — ONNX model loading, tokenization, embedding, similarity |
| `src/code_memory/mcp_tools.py` | Modify — add `search` tool, update `remember`/`index_project` to auto-embed |
| `src/code_memory/memory_manager.py` | Modify — embed on `remember`, similarity-based `recall` |
| `src/code_memory/db.py` | Modify — add `embeddings` table to schema |
| `src/code_memory/symbol_indexer.py` | Modify — batch-embed after indexing |
| `tests/test_embedding_engine.py` | **New** — unit tests for tokenize, embed, cosine similarity |
| `tests/test_search.py` | **New** — search ranking, relationship detection, fallback |
| `pyproject.toml` | Modify — add onnxruntime, tokenizers, huggingface_hub |
| `skills/memory-usage/SKILL.md` | Modify — recommend `search` over individual tools |

## Testing Strategy

- Unit tests for `EmbeddingEngine`: tokenize, embed, cosine similarity math
- Unit tests for `search`: mock the engine, verify ranking and relationship detection
- Integration test: index a small project, store memories, verify `search("Product Origin")` returns both symbols + relationship edges
- Fallback test: verify LIKE search works when model is unavailable
