# Semantic Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace SQL LIKE search with ONNX-based vector similarity search, add a unified `search` MCP tool.

**Architecture:** New `EmbeddingEngine` class wraps ONNX runtime + tokenizer for local embeddings. Vectors stored in SQLite `embeddings` table. A `search` tool queries across memories and symbols by cosine similarity, with automatic relationship detection via the dependency graph. Existing tools (`recall`, `query_symbols`) become thin wrappers.

**Tech Stack:** onnxruntime, tokenizers, huggingface_hub, numpy, all-MiniLM-L6-v2 int8 ONNX model

---

### Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add new dependencies to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list:

```toml
dependencies = [
    "mcp[cli]>=1.0.0",
    "tree-sitter>=0.21.0",
    "tree-sitter-python>=0.21.0",
    "tree-sitter-javascript>=0.21.0",
    "tree-sitter-typescript>=0.21.0",
    "tree-sitter-go>=0.21.0",
    "networkx>=3.0",
    "onnxruntime>=1.17.0",
    "tokenizers>=0.15.0",
    "huggingface-hub>=0.20.0",
    "numpy>=1.24.0",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: All packages install successfully.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add onnxruntime, tokenizers, huggingface-hub dependencies"
```

---

### Task 2: Add Embeddings Table to Schema

**Files:**
- Modify: `src/code_memory/db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_embeddings_table_exists(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    # Table should exist after initialize
    cursor = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'"
    )
    assert cursor.fetchone() is not None
    db.close()


def test_embeddings_insert_and_query(tmp_path):
    import struct

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    project_id = db.get_or_create_project("/test")
    # Store a 3-dim vector as BLOB
    vector = struct.pack("3f", 0.1, 0.2, 0.3)
    db.execute(
        "INSERT INTO embeddings (project_id, source_type, source_id, text, vector) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, "memory", 1, "test text", vector),
    )
    db.conn.commit()
    row = db.execute(
        "SELECT * FROM embeddings WHERE project_id = ? AND source_type = 'memory'",
        (project_id,),
    ).fetchone()
    assert row is not None
    assert dict(row)["text"] == "test text"
    db.close()


def test_embeddings_unique_constraint(tmp_path):
    import sqlite3
    import struct

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    project_id = db.get_or_create_project("/test")
    vector = struct.pack("3f", 0.1, 0.2, 0.3)
    db.execute(
        "INSERT INTO embeddings (project_id, source_type, source_id, text, vector) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, "memory", 1, "text1", vector),
    )
    db.conn.commit()
    # Same source_type + source_id should conflict
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO embeddings (project_id, source_type, source_id, text, vector) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, "memory", 1, "text2", vector),
        )
    db.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_embeddings_table_exists tests/test_db.py::test_embeddings_insert_and_query tests/test_db.py::test_embeddings_unique_constraint -v`
Expected: FAIL — table "embeddings" does not exist.

**Step 3: Add embeddings table to SCHEMA in db.py**

In `src/code_memory/db.py`, add to the `SCHEMA` string (after the `tool_usage` table):

```sql
CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,
    UNIQUE(project_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_project ON embeddings(project_id, source_type);
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All PASS, including new tests.

**Step 5: Commit**

```bash
git add src/code_memory/db.py tests/test_db.py
git commit -m "feat: add embeddings table to schema"
```

---

### Task 3: Create EmbeddingEngine — Model Download & Loading

**Files:**
- Create: `src/code_memory/embedding_engine.py`
- Create: `tests/test_embedding_engine.py`

**Step 1: Write the failing test for model download**

Create `tests/test_embedding_engine.py`:

```python
import numpy as np
import pytest

from src.code_memory.embedding_engine import EmbeddingEngine


@pytest.fixture
def engine(tmp_path):
    return EmbeddingEngine(model_dir=str(tmp_path / "models"))


class TestModelLoading:
    def test_engine_initializes(self, engine):
        assert engine is not None
        assert not engine.is_ready

    def test_engine_loads_model(self, engine):
        engine.ensure_ready()
        assert engine.is_ready
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embedding_engine.py::TestModelLoading -v`
Expected: FAIL — module not found.

**Step 3: Implement EmbeddingEngine with model download and loading**

Create `src/code_memory/embedding_engine.py`:

```python
from __future__ import annotations

import logging
import os
import struct
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_REPO = "Xenova/all-MiniLM-L6-v2"
MODEL_SUBDIR = "onnx"
MODEL_FILENAME = "model_quantized.onnx"
TOKENIZER_FILENAME = "tokenizer.json"
EMBEDDING_DIM = 384

DEFAULT_MODEL_DIR = str(Path.home() / ".code-memory" / "models" / "all-MiniLM-L6-v2-int8")


class EmbeddingEngine:
    def __init__(self, model_dir: str = DEFAULT_MODEL_DIR):
        self.model_dir = model_dir
        self._session = None
        self._tokenizer = None

    @property
    def is_ready(self) -> bool:
        return self._session is not None and self._tokenizer is not None

    def ensure_ready(self) -> None:
        if self.is_ready:
            return
        self._download_if_needed()
        self._load_model()

    def _download_if_needed(self) -> None:
        model_path = os.path.join(self.model_dir, MODEL_FILENAME)
        tokenizer_path = os.path.join(self.model_dir, TOKENIZER_FILENAME)
        if os.path.exists(model_path) and os.path.exists(tokenizer_path):
            return

        logger.info("Downloading embedding model (~23MB, one-time)...")
        os.makedirs(self.model_dir, exist_ok=True)

        from huggingface_hub import hf_hub_download

        hf_hub_download(
            repo_id=MODEL_REPO,
            filename=f"{MODEL_SUBDIR}/{MODEL_FILENAME}",
            local_dir=self.model_dir,
            local_dir_use_symlinks=False,
        )
        hf_hub_download(
            repo_id=MODEL_REPO,
            filename=TOKENIZER_FILENAME,
            local_dir=self.model_dir,
            local_dir_use_symlinks=False,
        )

        # Move from subdir to model_dir root if needed
        subdir_model = os.path.join(self.model_dir, MODEL_SUBDIR, MODEL_FILENAME)
        if os.path.exists(subdir_model) and not os.path.exists(model_path):
            os.rename(subdir_model, model_path)

        logger.info("Model downloaded successfully.")

    def _load_model(self) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = os.path.join(self.model_dir, MODEL_FILENAME)
        tokenizer_path = os.path.join(self.model_dir, TOKENIZER_FILENAME)

        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(tokenizer_path)
        self._tokenizer.enable_truncation(max_length=128)
        self._tokenizer.enable_padding(length=128)

    def embed(self, text: str) -> np.ndarray:
        self.ensure_ready()
        encoded = self._tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        # Mean pooling over token embeddings, masked by attention
        token_embeddings = outputs[0]  # (1, seq_len, 384)
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        # L2 normalize
        norm = np.linalg.norm(pooled, axis=1, keepdims=True)
        normalized = pooled / np.maximum(norm, 1e-12)
        return normalized[0]  # (384,)

    def embed_batch(self, texts: list[str]) -> np.ndarray:
        self.ensure_ready()
        if not texts:
            return np.empty((0, EMBEDDING_DIM), dtype=np.float32)
        encoded_batch = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded_batch], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encoded_batch], dtype=np.int64
        )
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )
        token_embeddings = outputs[0]
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)
        pooled = (token_embeddings * mask).sum(axis=1) / mask.sum(axis=1)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled / np.maximum(norms, 1e-12)

    @staticmethod
    def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
        if matrix.size == 0:
            return np.array([])
        return matrix @ query_vec

    @staticmethod
    def vector_to_blob(vec: np.ndarray) -> bytes:
        return vec.astype(np.float32).tobytes()

    @staticmethod
    def blob_to_vector(blob: bytes) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embedding_engine.py::TestModelLoading -v`
Expected: PASS (model downloads on first run — may take a few seconds).

**Step 5: Commit**

```bash
git add src/code_memory/embedding_engine.py tests/test_embedding_engine.py
git commit -m "feat: add EmbeddingEngine with ONNX model download and loading"
```

---

### Task 4: EmbeddingEngine — Embed, Batch Embed, Cosine Similarity

**Files:**
- Modify: `tests/test_embedding_engine.py`

**Step 1: Write the failing tests for embedding and similarity**

Add to `tests/test_embedding_engine.py`:

```python
class TestEmbedding:
    def test_embed_returns_384_dim_vector(self, engine):
        engine.ensure_ready()
        vec = engine.embed("hello world")
        assert vec.shape == (384,)
        assert vec.dtype == np.float32

    def test_embed_is_normalized(self, engine):
        engine.ensure_ready()
        vec = engine.embed("test sentence")
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5

    def test_embed_batch(self, engine):
        engine.ensure_ready()
        vecs = engine.embed_batch(["hello", "world", "test"])
        assert vecs.shape == (3, 384)

    def test_embed_batch_empty(self, engine):
        engine.ensure_ready()
        vecs = engine.embed_batch([])
        assert vecs.shape == (0, 384)

    def test_similar_texts_have_high_similarity(self, engine):
        engine.ensure_ready()
        v1 = engine.embed("Product class for e-commerce")
        v2 = engine.embed("Product model in the shop")
        v3 = engine.embed("completely unrelated weather forecast")
        sim_related = EmbeddingEngine.cosine_similarity(v1, v2.reshape(1, -1))[0]
        sim_unrelated = EmbeddingEngine.cosine_similarity(v1, v3.reshape(1, -1))[0]
        assert sim_related > sim_unrelated

    def test_word_order_invariance(self, engine):
        engine.ensure_ready()
        v1 = engine.embed("Product Origin relationship")
        v2 = engine.embed("Origin Product relationship")
        sim = EmbeddingEngine.cosine_similarity(v1, v2.reshape(1, -1))[0]
        # Should be very similar despite word order change
        assert sim > 0.85


class TestSerialization:
    def test_vector_roundtrip(self, engine):
        engine.ensure_ready()
        vec = engine.embed("test")
        blob = EmbeddingEngine.vector_to_blob(vec)
        restored = EmbeddingEngine.blob_to_vector(blob)
        np.testing.assert_array_almost_equal(vec, restored)
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_embedding_engine.py -v`
Expected: All PASS. The implementation already exists from Task 3.

**Step 3: Commit**

```bash
git add tests/test_embedding_engine.py
git commit -m "test: add embedding, similarity, and serialization tests"
```

---

### Task 5: Wire Embeddings into `remember` and `forget`

**Files:**
- Modify: `src/code_memory/memory_manager.py`
- Modify: `tests/test_memory_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_memory_manager.py`:

```python
def test_remember_stores_embedding(manager):
    manager.remember(file_path="app.py", symbol_name="login", notes="handles JWT auth")
    row = manager.db.execute(
        "SELECT * FROM embeddings WHERE project_id = ? AND source_type = 'memory'",
        (manager.project_id,),
    ).fetchone()
    assert row is not None
    assert "JWT" in dict(row)["text"]


def test_forget_deletes_embedding(manager):
    mid = manager.remember(file_path="app.py", notes="to be forgotten")
    manager.forget(mid)
    row = manager.db.execute(
        "SELECT * FROM embeddings WHERE project_id = ? AND source_type = 'memory' AND source_id = ?",
        (manager.project_id, mid),
    ).fetchone()
    assert row is None
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_manager.py::test_remember_stores_embedding tests/test_memory_manager.py::test_forget_deletes_embedding -v`
Expected: FAIL — no rows in embeddings table.

**Step 3: Modify MemoryManager to accept an optional EmbeddingEngine and store embeddings**

In `src/code_memory/memory_manager.py`:

```python
from __future__ import annotations

from src.code_memory.db import Database
from src.code_memory.git_utils import get_current_commit, has_file_changed


class MemoryManager:
    def __init__(self, db: Database, project_root: str, embedding_engine=None):
        self.db = db
        self.project_root = project_root
        self.project_id = db.get_or_create_project(project_root)
        self._embedding_engine = embedding_engine

    def _build_memory_text(
        self, notes: str, file_path: str | None, symbol_name: str | None
    ) -> str:
        parts = [notes]
        if symbol_name:
            parts.append(symbol_name)
        if file_path:
            parts.append(file_path)
        return " ".join(parts)

    def _store_embedding(
        self, source_type: str, source_id: int, text: str
    ) -> None:
        if self._embedding_engine is None:
            return
        try:
            self._embedding_engine.ensure_ready()
            vec = self._embedding_engine.embed(text)
            blob = self._embedding_engine.vector_to_blob(vec)
            self.db.execute(
                """INSERT OR REPLACE INTO embeddings
                   (project_id, source_type, source_id, text, vector)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, source_type, source_id, text, blob),
            )
            self.db.conn.commit()
        except Exception:
            pass  # Embedding failure should not block memory storage

    def _delete_embedding(self, source_type: str, source_id: int) -> None:
        self.db.execute(
            "DELETE FROM embeddings WHERE project_id = ? AND source_type = ? AND source_id = ?",
            (self.project_id, source_type, source_id),
        )
        self.db.conn.commit()

    def remember(
        self,
        notes: str,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> int:
        commit_hash = get_current_commit(self.project_root)
        cursor = self.db.execute(
            """INSERT INTO memories (project_id, file_path, symbol_name, notes, commit_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (self.project_id, file_path, symbol_name, notes, commit_hash),
        )
        self.db.conn.commit()
        memory_id = cursor.lastrowid
        text = self._build_memory_text(notes, file_path, symbol_name)
        self._store_embedding("memory", memory_id, text)
        return memory_id

    def recall(self, query: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, file_path, symbol_name, notes, commit_hash, is_stale,
                      created_at, updated_at
               FROM memories
               WHERE project_id = ?
                 AND (symbol_name LIKE ? OR file_path LIKE ? OR notes LIKE ?)
               ORDER BY updated_at DESC""",
            (self.project_id, f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()

        results = []
        for row in rows:
            memory = dict(row)
            memory["is_stale"] = bool(memory["is_stale"])
            if memory["file_path"] and memory["commit_hash"]:
                stale = has_file_changed(
                    self.project_root, memory["file_path"], memory["commit_hash"]
                )
                if stale and not memory["is_stale"]:
                    self.db.execute(
                        "UPDATE memories SET is_stale = TRUE WHERE id = ?",
                        (memory["id"],),
                    )
                    self.db.conn.commit()
                    memory["is_stale"] = True
            results.append(memory)
        return results

    def forget(self, memory_id: int) -> bool:
        cursor = self.db.execute(
            "DELETE FROM memories WHERE id = ? AND project_id = ?",
            (memory_id, self.project_id),
        )
        self.db.conn.commit()
        if cursor.rowcount > 0:
            self._delete_embedding("memory", memory_id)
            return True
        return False

    def get_project_summary(self) -> dict:
        total = self.db.execute(
            "SELECT COUNT(*) FROM memories WHERE project_id = ?",
            (self.project_id,),
        ).fetchone()[0]

        stale = self.db.execute(
            "SELECT COUNT(*) FROM memories WHERE project_id = ? AND is_stale = TRUE",
            (self.project_id,),
        ).fetchone()[0]

        recent = self.db.execute(
            """SELECT id, file_path, symbol_name, notes, is_stale, created_at
               FROM memories
               WHERE project_id = ?
               ORDER BY updated_at DESC
               LIMIT 10""",
            (self.project_id,),
        ).fetchall()

        return {
            "project_root": self.project_root,
            "total_memories": total,
            "stale_memories": stale,
            "recent_memories": [dict(r) for r in recent],
        }
```

Also update the `manager` fixture in `tests/test_memory_manager.py` to pass an `EmbeddingEngine`:

```python
from src.code_memory.embedding_engine import EmbeddingEngine

@pytest.fixture
def manager(git_repo, tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    engine = EmbeddingEngine()
    mgr = MemoryManager(db, str(git_repo), embedding_engine=engine)
    yield mgr
    db.close()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_manager.py -v`
Expected: All PASS (old + new tests).

**Step 5: Commit**

```bash
git add src/code_memory/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: store embeddings on remember, delete on forget"
```

---

### Task 6: Implement Semantic Search in MemoryManager

**Files:**
- Modify: `src/code_memory/memory_manager.py`
- Modify: `tests/test_memory_manager.py`

**Step 1: Write the failing test**

Add to `tests/test_memory_manager.py`:

```python
def test_semantic_search_finds_by_meaning(manager):
    manager.remember(file_path="models.py", symbol_name="Product", notes="e-commerce product model")
    manager.remember(file_path="auth.py", symbol_name="login", notes="handles user authentication")
    results = manager.semantic_search("shopping item class")
    assert len(results) > 0
    assert results[0]["source_type"] == "memory"
    assert "Product" in results[0]["notes"] or "product" in results[0]["notes"].lower()


def test_semantic_search_word_order_invariant(manager):
    manager.remember(notes="Product relates to Origin via foreign key")
    r1 = manager.semantic_search("Product Origin")
    r2 = manager.semantic_search("Origin Product")
    # Both should find the same memory
    assert len(r1) > 0
    assert len(r2) > 0
    assert r1[0]["source_id"] == r2[0]["source_id"]


def test_semantic_search_returns_empty_without_engine(git_repo, tmp_path):
    db = Database(str(tmp_path / "test2.db"))
    db.initialize()
    mgr = MemoryManager(db, str(git_repo), embedding_engine=None)
    mgr.remember(notes="some note")
    results = mgr.semantic_search("note")
    assert results == []
    db.close()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_memory_manager.py::test_semantic_search_finds_by_meaning -v`
Expected: FAIL — `MemoryManager` has no `semantic_search` method.

**Step 3: Add `semantic_search` method to MemoryManager**

Add to `src/code_memory/memory_manager.py`, inside the `MemoryManager` class:

```python
    def semantic_search(
        self, query: str, top_k: int = 10, source_type: str | None = None
    ) -> list[dict]:
        if self._embedding_engine is None:
            return []
        try:
            self._embedding_engine.ensure_ready()
        except Exception:
            return []

        import numpy as np

        # Build filter clause
        type_filter = ""
        params: list = [self.project_id]
        if source_type:
            type_filter = " AND source_type = ?"
            params.append(source_type)

        rows = self.db.execute(
            f"SELECT id, source_type, source_id, text, vector FROM embeddings "
            f"WHERE project_id = ?{type_filter}",
            tuple(params),
        ).fetchall()

        if not rows:
            return []

        query_vec = self._embedding_engine.embed(query)
        vectors = np.array(
            [self._embedding_engine.blob_to_vector(r["vector"]) for r in rows]
        )
        scores = self._embedding_engine.cosine_similarity(query_vec, vectors)

        # Sort by score descending, take top_k
        ranked_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in ranked_indices:
            row = dict(rows[idx])
            row["score"] = float(scores[idx])
            del row["vector"]  # Don't return raw bytes
            # Enrich with source data
            if row["source_type"] == "memory":
                mem = self.db.execute(
                    "SELECT id, file_path, symbol_name, notes, is_stale FROM memories WHERE id = ?",
                    (row["source_id"],),
                ).fetchone()
                if mem:
                    row.update(dict(mem))
            elif row["source_type"] == "symbol":
                sym = self.db.execute(
                    "SELECT symbol_name, symbol_type, file_path, line_start, line_end, signature "
                    "FROM symbols WHERE id = ?",
                    (row["source_id"],),
                ).fetchone()
                if sym:
                    row.update(dict(sym))
            results.append(row)
        return results
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_memory_manager.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/code_memory/memory_manager.py tests/test_memory_manager.py
git commit -m "feat: add semantic_search method to MemoryManager"
```

---

### Task 7: Wire Embeddings into `index_project`

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Create: `tests/test_search.py`

**Step 1: Write the failing test**

Create `tests/test_search.py`:

```python
import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.embedding_engine import EmbeddingEngine
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import index_project_files


@pytest.fixture
def project_with_symbols(tmp_path):
    """Create a git repo with two related classes."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=project, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=project, check=True, capture_output=True
    )

    (project / "models.py").write_text(
        "from origin import Origin\n\n"
        "class Product:\n"
        "    def __init__(self, name: str, origin: Origin):\n"
        "        self.name = name\n"
        "        self.origin = origin\n"
    )
    (project / "origin.py").write_text(
        "class Origin:\n"
        "    def __init__(self, country: str):\n"
        "        self.country = country\n"
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True
    )

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    engine = EmbeddingEngine()
    manager = MemoryManager(db, str(project), embedding_engine=engine)
    project_id = manager.project_id

    # Index symbols
    index_project_files(db, project_id, str(project))

    # Embed all symbols
    rows = db.execute(
        "SELECT id, symbol_name, symbol_type, signature, file_path FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    for row in rows:
        row = dict(row)
        text = f"{row['symbol_name']} {row['symbol_type']} {row['signature'] or ''} {row['file_path']}"
        vec = engine.embed(text)
        blob = engine.vector_to_blob(vec)
        db.execute(
            "INSERT OR REPLACE INTO embeddings (project_id, source_type, source_id, text, vector) "
            "VALUES (?, 'symbol', ?, ?, ?)",
            (project_id, row["id"], text, blob),
        )
    db.conn.commit()

    yield manager, db, project_id
    db.close()


def test_semantic_search_finds_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    results = manager.semantic_search("Product")
    symbol_names = [r.get("symbol_name", "") for r in results]
    assert "Product" in symbol_names


def test_semantic_search_word_order_for_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    r1 = manager.semantic_search("Product Origin")
    r2 = manager.semantic_search("Origin Product")
    # Both should return results
    assert len(r1) > 0
    assert len(r2) > 0
    # Top results should contain same symbols
    names1 = {r.get("symbol_name") for r in r1[:3]}
    names2 = {r.get("symbol_name") for r in r2[:3]}
    assert names1 & names2  # Overlap


def test_semantic_search_mixed_memories_and_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    manager.remember(notes="Product uses Origin via foreign key", file_path="models.py")
    results = manager.semantic_search("how Product connects to Origin")
    source_types = {r["source_type"] for r in results}
    assert "memory" in source_types
    assert "symbol" in source_types
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_search.py -v`
Expected: All PASS (the search logic is already in MemoryManager from Task 6, and the fixture does the embedding inline).

**Step 3: Add symbol embedding helper to mcp_tools.py**

In `src/code_memory/mcp_tools.py`, add a helper function and update the `_get_manager` function:

```python
from src.code_memory.embedding_engine import EmbeddingEngine

_engine: EmbeddingEngine | None = None


def _get_engine() -> EmbeddingEngine:
    global _engine
    if _engine is None:
        _engine = EmbeddingEngine()
    return _engine


def _get_manager() -> MemoryManager:
    global _manager
    if _manager is None:
        project_root = os.getcwd()
        db_path = default_db_path(project_root)
        db = Database(db_path)
        db.initialize()
        _manager = MemoryManager(db, project_root, embedding_engine=_get_engine())
    return _manager


def _embed_symbols(manager: MemoryManager, changed_files: list[str] | None = None) -> int:
    """Batch-embed all symbols (or only those in changed_files)."""
    engine = _get_engine()
    try:
        engine.ensure_ready()
    except Exception:
        return 0

    db = manager.db
    project_id = manager.project_id

    if changed_files is not None:
        # Delete old embeddings for changed files
        for f in changed_files:
            db.execute(
                """DELETE FROM embeddings WHERE project_id = ? AND source_type = 'symbol'
                   AND source_id IN (SELECT id FROM symbols WHERE project_id = ? AND file_path = ?)""",
                (project_id, project_id, f),
            )
    else:
        # Full re-embed: clear all symbol embeddings
        db.execute(
            "DELETE FROM embeddings WHERE project_id = ? AND source_type = 'symbol'",
            (project_id,),
        )

    # Fetch symbols to embed
    if changed_files:
        placeholders = ",".join("?" * len(changed_files))
        rows = db.execute(
            f"SELECT id, symbol_name, symbol_type, signature, file_path FROM symbols "
            f"WHERE project_id = ? AND file_path IN ({placeholders})",
            (project_id, *changed_files),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT id, symbol_name, symbol_type, signature, file_path FROM symbols "
            "WHERE project_id = ?",
            (project_id,),
        ).fetchall()

    if not rows:
        db.conn.commit()
        return 0

    texts = []
    for r in rows:
        r = dict(r)
        texts.append(
            f"{r['symbol_name']} {r['symbol_type']} {r['signature'] or ''} {r['file_path']}"
        )

    vectors = engine.embed_batch(texts)
    for i, r in enumerate(rows):
        r = dict(r)
        blob = engine.vector_to_blob(vectors[i])
        db.execute(
            "INSERT OR REPLACE INTO embeddings (project_id, source_type, source_id, text, vector) "
            "VALUES (?, 'symbol', ?, ?, ?)",
            (project_id, r["id"], texts[i], blob),
        )
    db.conn.commit()
    return len(rows)
```

Then update the `index_project` tool to call `_embed_symbols` after indexing:

In the `index_project` function, before the return statements that report success, add:

```python
    embedded = _embed_symbols(manager, changed_files)
```

And append to the return messages: e.g. `f" Embedded {embedded} symbols."`

**Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_search.py
git commit -m "feat: auto-embed symbols on index_project"
```

---

### Task 8: Add the `search` MCP Tool

**Files:**
- Modify: `src/code_memory/mcp_tools.py`

**Step 1: Write the failing test**

Add to `tests/test_search.py`:

```python
def test_search_tool_returns_formatted_output(project_with_symbols):
    manager, db, project_id = project_with_symbols
    manager.remember(notes="Product uses Origin via FK", file_path="models.py")

    # Simulate what the MCP search tool does
    results = manager.semantic_search("Product Origin")
    assert len(results) > 0
    # Verify results contain useful fields
    for r in results:
        assert "source_type" in r
        assert "score" in r
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_search.py::test_search_tool_returns_formatted_output -v`
Expected: PASS.

**Step 3: Add the `search` MCP tool**

In `src/code_memory/mcp_tools.py`, add:

```python
@mcp.tool(
    name="search",
    title="Search",
    description=(
        "Use when you need to find anything in the codebase."
        " Searches across memories and symbols using semantic similarity."
        " Detects relationships between symbols automatically."
    ),
)
def search(query: str, top_k: int = 10) -> str:
    """Unified semantic search across memories and symbols.

    Returns ranked results with relationship detection.
    Prefer this over recall() or query_symbols() for natural-language queries.

    Args:
        query: What to search for (natural language, symbol names, file paths)
        top_k: Maximum number of results (default 10)
    """
    top_k = min(top_k, 50)
    manager = _get_manager()
    results = manager.semantic_search(query, top_k=top_k)

    if not results:
        log_tool_usage(manager.db, manager.project_id, "search", f"query={query}", result_empty=True)
        return (
            "No results found. The embedding model may not be available,"
            " or the index may be empty — try running index_project first."
        )

    lines = []
    symbol_names = []

    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        if r["source_type"] == "memory":
            stale_flag = " [STALE]" if r.get("is_stale") else ""
            symbol = f" ({r['symbol_name']})" if r.get("symbol_name") else ""
            file_info = f" in {r['file_path']}" if r.get("file_path") else ""
            lines.append(
                f"{i}. [memory]{stale_flag}{file_info}{symbol}: {r.get('notes', '')}"
            )
        elif r["source_type"] == "symbol":
            stype = r.get("symbol_type", "")
            sname = r.get("symbol_name", "")
            fpath = r.get("file_path", "")
            lstart = r.get("line_start", "")
            lend = r.get("line_end", "")
            sig = r.get("signature", "")
            lines.append(f"{i}. [symbol] {stype} {sname} in {fpath}:{lstart}-{lend}")
            if sig:
                lines.append(f"   {sig}")
            symbol_names.append(sname)

    # Relationship detection: check dependency graph for edges between found symbols
    if len(set(symbol_names)) >= 2:
        graph = _ensure_graph_loaded()
        unique_symbols = list(set(symbol_names))
        for i_sym in range(len(unique_symbols)):
            for j_sym in range(i_sym + 1, len(unique_symbols)):
                a, b = unique_symbols[i_sym], unique_symbols[j_sym]
                deps_a = graph.get_dependencies(a)
                deps_b = graph.get_dependencies(b)
                a_to_b = [d for d in deps_a if d["symbol_name"] == b]
                b_to_a = [d for d in deps_b if d["symbol_name"] == a]
                rel_lines = []
                for d in a_to_b:
                    rel_lines.append(f"  {a} --{d['dep_type']}--> {b}")
                for d in b_to_a:
                    rel_lines.append(f"  {b} --{d['dep_type']}--> {a}")
                if rel_lines:
                    lines.append(f"\n[relationship] {a} <-> {b}:")
                    lines.extend(rel_lines)

    log_tool_usage(manager.db, manager.project_id, "search", f"query={query}", result_empty=False)
    return "\n".join(lines)
```

**Step 4: Update `recall` and `query_symbols` to use semantic search with fallback**

In `src/code_memory/mcp_tools.py`, update the `recall` function body:

```python
def recall(query: str) -> str:
    manager = _get_manager()
    # Try semantic search first
    results = manager.semantic_search(query, source_type="memory")
    if results:
        lines = []
        for m in results:
            stale_flag = " [STALE]" if m.get("is_stale") else ""
            symbol = f" ({m['symbol_name']})" if m.get("symbol_name") else ""
            file_info = f" in {m['file_path']}" if m.get("file_path") else ""
            lines.append(f"#{m.get('source_id', m.get('id', '?'))}{stale_flag}{file_info}{symbol}: {m.get('notes', '')}")
        log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=False)
        return "\n".join(lines)

    # Fallback to LIKE search
    results = manager.recall(query)
    if not results:
        log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=True)
        return (
            "No memories found. Use remember() to store context,"
            " or run index_project then try query_symbols."
        )
    lines = []
    for m in results:
        stale_flag = " [STALE]" if m["is_stale"] else ""
        symbol = f" ({m['symbol_name']})" if m["symbol_name"] else ""
        file_info = f" in {m['file_path']}" if m["file_path"] else ""
        lines.append(f"#{m['id']}{stale_flag}{file_info}{symbol}: {m['notes']}")
    log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=False)
    return "\n".join(lines)
```

Similarly update `query_symbols`:

```python
def query_symbols(name: str) -> str:
    manager = _get_manager()
    # Try semantic search first
    results = manager.semantic_search(name, source_type="symbol")
    if results:
        lines = []
        for s in results:
            lines.append(
                f"{s.get('symbol_type', '')} {s.get('symbol_name', '')}"
                f" in {s.get('file_path', '')}:{s.get('line_start', '')}-{s.get('line_end', '')}"
            )
            if s.get("signature"):
                lines.append(f"  {s['signature']}")
        log_tool_usage(manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=False)
        return "\n".join(lines)

    # Fallback to LIKE search
    results = query_symbol(manager.db, manager.project_id, name)
    if not results:
        log_tool_usage(manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=True)
        return f"No symbols found matching '{name}'. Try running index_project first."
    lines = []
    for s in results:
        lines.append(
            f"{s['symbol_type']} {s['symbol_name']}"
            f" in {s['file_path']}:{s['line_start']}-{s['line_end']}"
        )
        if s.get("signature"):
            lines.append(f"  {s['signature']}")
    log_tool_usage(manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=False)
    return "\n".join(lines)
```

**Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_search.py
git commit -m "feat: add unified search MCP tool with relationship detection"
```

---

### Task 9: Add Search Integration Test with Relationship Detection

**Files:**
- Modify: `tests/test_search.py`

**Step 1: Write the integration test**

Add to `tests/test_search.py`:

```python
def test_search_detects_relationships(project_with_symbols):
    """Product imports Origin — search should detect this relationship."""
    manager, db, project_id = project_with_symbols

    from src.code_memory.graph_engine import CodeGraph

    graph = CodeGraph()
    graph.build_from_db(db, project_id)

    # Verify the dependency exists in the graph
    deps = graph.get_dependencies("Product")
    dep_names = [d["symbol_name"] for d in deps]
    # Product should have some dependency on Origin (via import)
    assert "Origin" in dep_names or len(deps) > 0

    # Now test semantic search returns both
    results = manager.semantic_search("Product Origin")
    names = [r.get("symbol_name") for r in results]
    assert "Product" in names or "Origin" in names
```

**Step 2: Run test**

Run: `uv run pytest tests/test_search.py::test_search_detects_relationships -v`
Expected: PASS.

**Step 3: Commit**

```bash
git add tests/test_search.py
git commit -m "test: add relationship detection integration test"
```

---

### Task 10: Update Skill and Bump Version

**Files:**
- Modify: `skills/memory-usage/SKILL.md`
- Modify: `pyproject.toml`

**Step 1: Update the memory-usage skill to recommend `search`**

Replace contents of `skills/memory-usage/SKILL.md`:

```markdown
---
name: memory-usage
description: "IMPORTANT: Before searching code, reading files, or exploring the codebase, use code-memory MCP tools for persistent context. Use search() as your primary tool — it replaces recall, query_symbols, and more with unified semantic search."
---

## Code Memory — Mandatory Usage

You have persistent memory and semantic code search via the code-memory MCP server. You MUST use these tools before falling back to Grep/Glob/Read.

### Session Start (REQUIRED)

Every session, before doing anything else:
1. Call `get_project_summary` to load existing memories
2. If the response says the index is empty or stale, call `index_project`
3. If the user's request relates to existing code, call `search` with the topic

### Decision Tree for Code Exploration

**Need to find anything — functions, classes, concepts, relationships?**
→ MUST use `search("your question")` first. It searches across memories AND symbols semantically. Only use Grep if search returns no results.

**Need to understand how two things relate?**
→ MUST use `search("Thing1 Thing2")`. It auto-detects relationships via the dependency graph.

**Need to know who calls a function?**
→ Use `get_callers("symbol_name")` for exact reverse lookups. Use `search` for fuzzy/semantic queries.

**Need to trace a call path?**
→ Use `trace_call_chain("from", "to")` for exact path finding.

**Need to read actual file contents?**
→ This is fine — use Read. But only AFTER checking search first.

### Storing Context (REQUIRED)

When you discover something important about the code:
- Call `remember` with concise notes focused on "why" and "how"
- Link to specific files and symbols for better recall
- Memories are automatically embedded for semantic search

### What NOT to Do

- Do NOT use Grep to find function definitions — use `search`
- Do NOT use Grep to find callers — use `get_callers` or `search`
- Do NOT skip `search` when starting work on a topic you may have seen before
- Do NOT ignore the session-start checklist
```

**Step 2: Bump version in pyproject.toml**

Change `version = "0.6.0"` to `version = "0.7.0"` in `pyproject.toml`.

**Step 3: Commit**

```bash
git add skills/memory-usage/SKILL.md pyproject.toml
git commit -m "feat: update skill to recommend search, bump to 0.7.0"
```

---

### Task 11: Run Full Test Suite and Verify

**Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS.

**Step 2: Manual smoke test**

Run the MCP server and verify search works:
```bash
uv run python -m src.code_memory
```

In a separate terminal, test with Claude Code or MCP Inspector that:
- `index_project` now reports embedding count
- `search("some concept")` returns ranked results
- `recall` uses semantic search
- `query_symbols` uses semantic search

**Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: address issues found in smoke testing"
```
