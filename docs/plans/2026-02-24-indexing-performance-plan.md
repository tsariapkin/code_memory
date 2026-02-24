# Indexing Performance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `index_project()` incremental and 2x faster on full reindex by eliminating double-parsing and N+1 queries.

**Architecture:** Three independent optimizations layered together: (1) `git diff` to detect changed files and skip unchanged ones, (2) single-pass file parsing that extracts symbols and dependencies together, (3) batched DB writes using a preloaded symbol-ID map and `executemany()`.

**Tech Stack:** Python 3.10+, tree-sitter, SQLite, git subprocess

---

### Task 1: Add `get_changed_files()` to git_utils

**Files:**
- Modify: `src/code_memory/git_utils.py`
- Test: `tests/test_git_utils.py`

**Step 1: Write the failing test**

Add to `tests/test_git_utils.py`:

```python
from src.code_memory.git_utils import get_changed_files


def test_get_changed_files_returns_changed(git_repo):
    commit = get_current_commit(str(git_repo))

    # Add a new .py file and modify existing
    (git_repo / "new_file.py").write_text("y = 2\n")
    (git_repo / "hello.py").write_text("x = 99\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "changes"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    changed = get_changed_files(str(git_repo), commit)
    assert "hello.py" in changed
    assert "new_file.py" in changed


def test_get_changed_files_empty_when_no_changes(git_repo):
    commit = get_current_commit(str(git_repo))
    changed = get_changed_files(str(git_repo), commit)
    assert changed == []


def test_get_changed_files_includes_deleted(git_repo):
    commit = get_current_commit(str(git_repo))

    (git_repo / "hello.py").unlink()
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "delete"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    changed = get_changed_files(str(git_repo), commit)
    assert "hello.py" in changed
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_git_utils.py -v`
Expected: ImportError — `get_changed_files` does not exist

**Step 3: Implement `get_changed_files`**

Add to `src/code_memory/git_utils.py`:

```python
def get_changed_files(
    repo_path: str, since_commit: str, extension: str = ".py"
) -> list[str]:
    """Return list of files changed since a commit, filtered by extension."""
    result = subprocess.run(
        ["git", "diff", "--name-only", since_commit, "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    files = [f for f in result.stdout.strip().splitlines() if f]
    if extension:
        files = [f for f in files if f.endswith(extension)]
    return files
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_git_utils.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/code_memory/git_utils.py tests/test_git_utils.py
git commit -m "feat: add get_changed_files to git_utils"
```

---

### Task 2: Add `update_last_indexed_commit()` to db

**Files:**
- Modify: `src/code_memory/db.py`
- Test: `tests/test_db.py`

**Step 1: Write the failing tests**

Add to `tests/test_db.py`:

```python
def test_update_and_get_last_indexed_commit(db):
    project_id = db.get_or_create_project("/some/path")

    # Initially null
    commit = db.get_last_indexed_commit(project_id)
    assert commit is None

    # Update
    db.update_last_indexed_commit(project_id, "abc123def456")
    commit = db.get_last_indexed_commit(project_id)
    assert commit == "abc123def456"

    # Update again
    db.update_last_indexed_commit(project_id, "new_commit_hash")
    commit = db.get_last_indexed_commit(project_id)
    assert commit == "new_commit_hash"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_update_and_get_last_indexed_commit -v`
Expected: AttributeError — method does not exist

**Step 3: Implement the methods**

Add to `Database` class in `src/code_memory/db.py`:

```python
def get_last_indexed_commit(self, project_id: int) -> str | None:
    row = self.execute(
        "SELECT last_indexed_commit FROM project WHERE id = ?",
        (project_id,),
    ).fetchone()
    return row[0] if row else None

def update_last_indexed_commit(self, project_id: int, commit_hash: str) -> None:
    self.execute(
        "UPDATE project SET last_indexed_commit = ? WHERE id = ?",
        (commit_hash, project_id),
    )
    self.conn.commit()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/code_memory/db.py tests/test_db.py
git commit -m "feat: add last_indexed_commit helpers to Database"
```

---

### Task 3: Cache the tree-sitter parser as a singleton

**Files:**
- Modify: `src/code_memory/symbol_indexer.py`
- Test: `tests/test_symbol_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_symbol_indexer.py`:

```python
from src.code_memory.symbol_indexer import _get_parser


def test_parser_is_cached():
    p1 = _get_parser()
    p2 = _get_parser()
    assert p1 is p2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_symbol_indexer.py::test_parser_is_cached -v`
Expected: ImportError — `_get_parser` does not exist

**Step 3: Implement the cached parser**

In `src/code_memory/symbol_indexer.py`, replace:

```python
def _make_parser() -> Parser:
    return Parser(PY_LANGUAGE)
```

With:

```python
_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        _parser = Parser(PY_LANGUAGE)
    return _parser
```

Then update `parse_file_symbols()` line 36 and `extract_dependencies()` line 245: change `_make_parser()` to `_get_parser()`.

**Step 4: Run all tests to verify nothing broke**

Run: `uv run pytest tests/ -v`
Expected: All 35+ tests pass

**Step 5: Commit**

```bash
git add src/code_memory/symbol_indexer.py tests/test_symbol_indexer.py
git commit -m "refactor: cache tree-sitter parser as singleton"
```

---

### Task 4: Create unified `index_project_files()` with single-pass parsing

**Files:**
- Modify: `src/code_memory/symbol_indexer.py`
- Test: `tests/test_project_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_project_indexer.py`:

```python
from src.code_memory.symbol_indexer import index_project_files


def test_index_project_files_returns_both_counts(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    sym_count, dep_count = index_project_files(db, project_id, str(python_project))
    assert sym_count >= 3  # login, verify, hashlib import
    assert dep_count >= 1  # login -> verify


def test_index_project_files_is_idempotent(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    sym1, dep1 = index_project_files(db, project_id, str(python_project))
    sym2, dep2 = index_project_files(db, project_id, str(python_project))
    assert sym1 == sym2
    assert dep1 == dep2

    total_syms = db.execute(
        "SELECT COUNT(*) FROM symbols WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    assert total_syms == sym1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_project_indexer.py::test_index_project_files_returns_both_counts -v`
Expected: ImportError — `index_project_files` does not exist

**Step 3: Implement `index_project_files()`**

Add to `src/code_memory/symbol_indexer.py`. This function:
1. Walks the project once, collecting Python file paths
2. Parses each file once with `_get_parser()`
3. Extracts symbols via `parse_file_symbols()`
4. Extracts dependencies via `extract_dependencies()`
5. Inserts all symbols, then batch-inserts dependencies using a preloaded symbol map

```python
SKIP_DIRS = {"__pycache__", "node_modules", ".venv", "venv"}


def _collect_python_files(
    project_root: str, only_files: list[str] | None = None
) -> list[tuple[str, str]]:
    """Collect (full_path, rel_path) pairs for Python files.

    If only_files is given, return only those relative paths (that exist).
    """
    if only_files is not None:
        result = []
        for rel in only_files:
            full = os.path.join(project_root, rel)
            if rel.endswith(".py") and os.path.isfile(full):
                result.append((full, rel))
        return result

    result = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        # Prune skipped directories in-place
        dirnames[:] = [
            d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
        ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, project_root)
            result.append((full_path, rel_path))
    return result


def index_project_files(
    db, project_id: int, project_root: str, changed_files: list[str] | None = None
) -> tuple[int, int]:
    """Parse Python files and store symbols + dependencies in one pass.

    If changed_files is provided, only index those files (incremental mode).
    Returns (symbol_count, dependency_count).
    """
    files = _collect_python_files(project_root, changed_files)

    if changed_files is not None:
        # Delete old symbols and deps for changed files
        for _, rel_path in files:
            db.execute(
                """DELETE FROM dependencies WHERE source_id IN
                   (SELECT id FROM symbols
                    WHERE project_id = ? AND file_path = ?)""",
                (project_id, rel_path),
            )
            db.execute(
                "DELETE FROM symbols WHERE project_id = ? AND file_path = ?",
                (project_id, rel_path),
            )
        # Also clean up deleted files (in changed_files but not on disk)
        for rel in changed_files:
            if rel.endswith(".py"):
                full = os.path.join(project_root, rel)
                if not os.path.isfile(full):
                    db.execute(
                        """DELETE FROM dependencies WHERE source_id IN
                           (SELECT id FROM symbols
                            WHERE project_id = ? AND file_path = ?)""",
                        (project_id, rel),
                    )
                    db.execute(
                        "DELETE FROM symbols WHERE project_id = ? AND file_path = ?",
                        (project_id, rel),
                    )

    # Phase 1: Parse files and insert symbols
    sym_count = 0
    all_deps = []

    for full_path, rel_path in files:
        try:
            symbols = parse_file_symbols(full_path)
        except Exception:
            continue

        for sym in symbols:
            db.execute(
                """INSERT OR REPLACE INTO symbols
                   (project_id, file_path, symbol_name, symbol_type,
                    line_start, line_end, signature, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    rel_path,
                    sym["symbol_name"],
                    sym["symbol_type"],
                    sym["line_start"],
                    sym["line_end"],
                    sym["signature"],
                    sym["content_hash"],
                ),
            )
            sym_count += 1

        try:
            deps = extract_dependencies(full_path)
            all_deps.extend(deps)
        except Exception:
            continue

    db.conn.commit()

    # Phase 2: Batch-insert dependencies using preloaded symbol map
    if changed_files is None:
        # Full reindex: clear all deps first
        db.execute(
            """DELETE FROM dependencies WHERE source_id IN
               (SELECT id FROM symbols WHERE project_id = ?)""",
            (project_id,),
        )

    rows = db.execute(
        "SELECT id, symbol_name FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    symbol_map = {row["symbol_name"]: row["id"] for row in rows}

    dep_rows = []
    for dep in all_deps:
        source_id = symbol_map.get(dep["source"])
        target_id = symbol_map.get(dep["target"])
        if source_id and target_id:
            dep_rows.append((source_id, target_id, dep["dep_type"]))

    if dep_rows:
        db.conn.executemany(
            "INSERT OR IGNORE INTO dependencies"
            " (source_id, target_id, dep_type) VALUES (?, ?, ?)",
            dep_rows,
        )
    db.conn.commit()

    return sym_count, len(dep_rows)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_project_indexer.py -v`
Expected: All pass (old and new tests)

**Step 5: Commit**

```bash
git add src/code_memory/symbol_indexer.py tests/test_project_indexer.py
git commit -m "feat: add index_project_files with single-pass parsing and batched deps"
```

---

### Task 5: Add incremental indexing test

**Files:**
- Test: `tests/test_incremental_indexing.py` (new)

**Step 1: Write the test**

```python
import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.git_utils import get_current_commit
from src.code_memory.symbol_indexer import index_project_files, query_symbol


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def git_project(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    (tmp_path / "auth.py").write_text(
        "def login(user, password):\n    return verify(user, password)\n"
    )
    (tmp_path / "utils.py").write_text(
        'def verify(user, password):\n    return user == "admin"\n'
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_incremental_indexes_only_changed_files(db, git_project):
    project_id = db.get_or_create_project(str(git_project))

    # Full index
    sym1, dep1 = index_project_files(db, project_id, str(git_project))
    assert sym1 >= 2  # login, verify

    # Modify one file
    (git_project / "auth.py").write_text(
        "def login_v2(user, password):\n    return verify(user, password)\n"
    )
    subprocess.run(
        ["git", "add", "."], cwd=git_project, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "rename"],
        cwd=git_project,
        check=True,
        capture_output=True,
    )

    # Incremental index with only auth.py
    sym2, dep2 = index_project_files(
        db, project_id, str(git_project), changed_files=["auth.py"]
    )
    assert sym2 >= 1  # login_v2

    # Old symbol gone, new symbol present
    results = query_symbol(db, project_id, "login")
    names = [r["symbol_name"] for r in results]
    assert "login" not in names
    assert "login_v2" in names

    # verify still present (was not in changed_files)
    results = query_symbol(db, project_id, "verify")
    assert len(results) == 1


def test_incremental_handles_deleted_files(db, git_project):
    project_id = db.get_or_create_project(str(git_project))

    # Full index
    index_project_files(db, project_id, str(git_project))

    # Delete a file
    (git_project / "utils.py").unlink()
    subprocess.run(
        ["git", "add", "."], cwd=git_project, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "commit", "-m", "delete utils"],
        cwd=git_project,
        check=True,
        capture_output=True,
    )

    # Incremental with deleted file
    index_project_files(
        db, project_id, str(git_project), changed_files=["utils.py"]
    )

    # verify symbol should be gone
    results = query_symbol(db, project_id, "verify")
    assert len(results) == 0

    # login should still exist
    results = query_symbol(db, project_id, "login")
    assert len(results) == 1
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_incremental_indexing.py -v`
Expected: All pass (uses `index_project_files` from Task 4)

**Step 3: Commit**

```bash
git add tests/test_incremental_indexing.py
git commit -m "test: add incremental indexing tests"
```

---

### Task 6: Wire up `index_project()` MCP tool to use new function with incremental support

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: run full test suite

**Step 1: Update the import and tool implementation**

In `src/code_memory/mcp_tools.py`, change the import:

```python
from src.code_memory.symbol_indexer import (
    get_symbol_dependencies,
    index_project_files,
    query_symbol,
)
```

Remove `build_project_dependencies` and `index_project_symbols` from imports.

Update the `index_project()` tool:

```python
@mcp.tool()
def index_project() -> str:
    """Index all Python files in the current project.

    Extracts functions, classes, methods, imports, and their dependencies.
    Run this when starting work on a new project or after major refactors.
    """
    manager = _get_manager()
    db = manager.db
    project_id = manager.project_id
    project_root = manager.project_root

    # Check for incremental indexing
    last_commit = db.get_last_indexed_commit(project_id)
    changed_files = None

    if last_commit:
        from src.code_memory.git_utils import get_changed_files, get_current_commit

        current = get_current_commit(project_root)
        if current == last_commit:
            return "No changes since last index."
        changed_files = get_changed_files(project_root, last_commit)
        if not changed_files:
            return "No Python files changed since last index."

    sym_count, dep_count = index_project_files(
        db, project_id, project_root, changed_files
    )

    # Update last indexed commit
    from src.code_memory.git_utils import get_current_commit

    current_commit = get_current_commit(project_root)
    db.update_last_indexed_commit(project_id, current_commit)

    if changed_files:
        return (
            f"Incremental index: {sym_count} symbols and"
            f" {dep_count} dependencies in {len(changed_files)} files."
        )
    return f"Indexed {sym_count} symbols and {dep_count} dependencies."
```

**Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

**Step 3: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: All checks passed

**Step 4: Commit**

```bash
git add src/code_memory/mcp_tools.py
git commit -m "feat: wire index_project to use incremental single-pass indexing"
```

---

### Task 7: Update existing tests to use new function names

**Files:**
- Modify: `tests/test_dependencies.py`
- Modify: `tests/test_phase2_integration.py`

**Step 1: Update test_dependencies.py**

The `test_get_symbol_dependencies` test calls `index_project_symbols` then `build_project_dependencies` separately. Update to call `index_project_files`:

```python
from src.code_memory.symbol_indexer import (
    extract_dependencies,
    get_symbol_dependencies,
    index_project_files,
)

# In test_get_symbol_dependencies:
def test_get_symbol_dependencies(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    index_project_files(db, project_id, str(python_project))

    deps = get_symbol_dependencies(db, project_id, "login")
    dep_names = [d["symbol_name"] for d in deps]
    assert "verify" in dep_names
```

**Step 2: Update test_phase2_integration.py**

Replace `index_project_symbols` + `build_project_dependencies` with `index_project_files`:

```python
from src.code_memory.symbol_indexer import (
    get_symbol_dependencies,
    index_project_files,
    query_symbol,
)

# In test_full_phase2_workflow, replace the two calls:
    sym_count, dep_count = index_project_files(db, project_id, str(project))
    assert sym_count >= 5
    assert dep_count >= 1
```

**Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests pass

**Step 4: Run linter**

Run: `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
Expected: All clean

**Step 5: Commit**

```bash
git add tests/test_dependencies.py tests/test_phase2_integration.py
git commit -m "refactor: update tests to use index_project_files"
```

---

### Task 8: Clean up deprecated functions

**Files:**
- Modify: `src/code_memory/symbol_indexer.py`

**Step 1: Remove old functions**

Remove `index_project_symbols()` and `build_project_dependencies()` from `symbol_indexer.py`. Keep `parse_file_symbols()`, `extract_dependencies()`, `find_enclosing_symbol()`, `query_symbol()`, `get_symbol_dependencies()`, and all private helpers (`_collect_calls`, `_find_enclosing_func`, `_content_hash`, `_extract_signature`, `_get_parser`, `_collect_python_files`).

**Step 2: Update test_project_indexer.py imports**

Remove `index_project_symbols` from the import, use `index_project_files` for all tests:

```python
from src.code_memory.symbol_indexer import index_project_files, query_symbol
```

Update existing tests that call `index_project_symbols`:
- `test_index_project_finds_all_symbols`: change to `sym_count, dep_count = index_project_files(...)` and assert `sym_count >= 3`
- `test_index_project_is_idempotent`: same treatment
- `test_query_symbol_returns_details` and `test_query_symbol_partial_match`: replace `index_project_symbols` with `index_project_files`

**Step 3: Run full test suite and linter**

Run: `uv run pytest tests/ -v && uv run ruff check src/ tests/`
Expected: All pass, all clean

**Step 4: Commit**

```bash
git add src/code_memory/symbol_indexer.py tests/test_project_indexer.py
git commit -m "refactor: remove deprecated index_project_symbols and build_project_dependencies"
```
