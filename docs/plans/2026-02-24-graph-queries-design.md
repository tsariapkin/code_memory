# Graph Query Engine with NetworkX

**Date:** 2026-02-24
**Status:** Approved

## Problem

The current `dependencies` table models a graph as an adjacency list in SQLite, but only supports forward "calls" edges. Users need:
- Reverse traversal ("who calls this function?")
- Richer relationship types (inheritance, imports)
- Multi-hop traversal ("show the call chain from endpoint to DB query")

These are painful to express in SQL and scale poorly with recursive CTEs on larger codebases.

## Design

Use NetworkX as an in-memory graph query engine over the existing SQLite storage. No new database — SQLite remains the single persistence layer. The graph is built from SQLite on demand and provides traversal capabilities.

### Architecture

```
SQLite (persistence)          NetworkX (query engine)
┌──────────────────┐          ┌──────────────────┐
│ project          │          │ DiGraph           │
│ memories         │          │   nodes: symbols  │
│ symbols ─────────┼──build──>│   edges: deps     │
│ dependencies     │          │                   │
└──────────────────┘          └──────────────────┘
```

Storage path unchanged: `~/.code-memory/<hash>.db`

### Relationship Types

The `dependencies.dep_type` column expands from just `"calls"` to:

| dep_type | Meaning | Example |
|----------|---------|---------|
| `calls` | Function/method call | `login` calls `validate_jwt` |
| `imports` | Import dependency | `auth.py::login` imports `jwt` |
| `inherits` | Class inheritance | `UserService` inherits `BaseService` |

Reverse relationships (`called_by`, `imported_by`) are not stored — NetworkX provides them via `predecessors()` / `in_edges()`.

### New Module: `graph_engine.py`

```python
class CodeGraph:
    def __init__(self):
        self.graph = nx.DiGraph()

    def build_from_db(self, db, project_id) -> None
    def get_callers(self, symbol_name) -> list[dict]
    def get_dependencies(self, symbol_name) -> list[dict]
    def trace_call_chain(self, from_sym, to_sym, max_depth=5) -> list[list[str]]
    def get_inheritance_chain(self, class_name) -> list[str]
    def invalidate(self) -> None
```

- Nodes carry attributes: `symbol_type`, `file_path`, `line_start`, `line_end`, `signature`
- Edges carry `dep_type` attribute
- Rebuilt after `index_project()` (via `invalidate()`) and lazily on first query
- 50K nodes + edges: ~50-100ms build time

### Indexer Changes

`symbol_indexer.py` additions (extraction logic only — storage stays in SQLite):

1. **Class inheritance extraction**: Read `argument_list` from `class_definition` AST nodes to produce `inherits` edges
2. **Import edge extraction**: Connect functions/classes to the names they import, producing `imports` edges
3. After indexing, call `graph.invalidate()` to force rebuild on next query

No changes to: `parse_file_symbols` return format, `find_enclosing_symbol`, `_collect_calls`, `_find_enclosing_func`, `_collect_python_files`.

### Schema Changes

```sql
-- Add language column to symbols (for future multi-language support)
ALTER TABLE symbols ADD COLUMN language TEXT DEFAULT 'python';

-- Add index on dep_type for filtered queries
CREATE INDEX IF NOT EXISTS idx_deps_type ON dependencies(dep_type);
```

### MCP Tools

Existing tools (unchanged signatures):

| Tool | Change |
|------|--------|
| `query_symbols(name)` | Also queries via CodeGraph |
| `get_dependencies(symbol_name)` | Delegates to CodeGraph |
| `index_project()` | Calls `graph.invalidate()` after indexing |
| `remember/recall/forget/get_project_summary` | No changes |

New tools:

| Tool | Description |
|------|-------------|
| `get_callers(symbol_name)` | Reverse traversal — who calls this? |
| `trace_call_chain(from_symbol, to_symbol, max_depth=5)` | All simple paths between two symbols |

Total: 9 MCP tools (7 existing + 2 new).

## Files Changed

| File | Action |
|------|--------|
| `graph_engine.py` | New — NetworkX wrapper |
| `symbol_indexer.py` | Add inheritance + import edge extraction |
| `mcp_tools.py` | Init CodeGraph, add 2 new tools, wire graph queries |
| `db.py` | Add `language` column to symbols, add index on `dep_type` |
| `pyproject.toml` | Add `networkx>=3.0` dependency |
| Tests | Update existing, add graph traversal tests |

## Constraints

- All 7 existing MCP tool signatures unchanged
- SQLite remains the only persistence layer
- No external database server required
- Language-agnostic schema (language field on symbols, generic dep_type)
- Scales to 50K symbols comfortably
