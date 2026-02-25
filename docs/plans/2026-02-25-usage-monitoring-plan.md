# Usage Monitoring & Stronger Nudges Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Break the "tools unused → empty results → tools avoided" feedback loop by adding usage logging, stronger nudges, and auto-bootstrap behavior.

**Architecture:** Add a `tool_usage` table to the existing SQLite DB. Wrap each MCP tool with a lightweight logging decorator. Add a `get_usage_stats` MCP tool. Rewrite skill/hook text to be directive. Enhance empty-result responses to suggest indexing.

**Tech Stack:** Python, SQLite, FastMCP, existing test infrastructure (pytest, tmp_path fixtures)

---

### Task 1: Add `tool_usage` table to DB schema

**Files:**
- Modify: `src/code_memory/db.py:5-52` (SCHEMA string)
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_tool_usage_table_exists(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='tool_usage'"
    ).fetchall()
    assert len(tables) == 1


def test_tool_usage_insert_and_query(db):
    import time

    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO tool_usage (tool_name, project_id, timestamp, args_summary, result_empty)
           VALUES (?, ?, ?, ?, ?)""",
        ("recall", project_id, time.time(), "query=auth", False),
    )
    db.conn.commit()
    rows = db.execute("SELECT * FROM tool_usage WHERE project_id = ?", (project_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "recall"
    assert rows[0]["result_empty"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_tool_usage_table_exists tests/test_db.py::test_tool_usage_insert_and_query -v`
Expected: FAIL — table `tool_usage` does not exist

**Step 3: Add the table to SCHEMA**

In `src/code_memory/db.py`, append to the `SCHEMA` string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS tool_usage (
    id INTEGER PRIMARY KEY,
    tool_name TEXT NOT NULL,
    project_id INTEGER REFERENCES project(id),
    timestamp REAL NOT NULL,
    args_summary TEXT,
    result_empty BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_tool_usage_project ON tool_usage(project_id, timestamp);
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/code_memory/db.py tests/test_db.py
git commit -m "feat: add tool_usage table to schema"
```

---

### Task 2: Add usage logging decorator

**Files:**
- Create: `src/code_memory/usage_logger.py`
- Test: `tests/test_usage_logger.py`

**Step 1: Write the failing test**

Create `tests/test_usage_logger.py`:

```python
import time

import pytest

from src.code_memory.db import Database
from src.code_memory.usage_logger import log_tool_usage, get_usage_stats


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


def test_log_tool_usage_inserts_row(db):
    project_id = db.get_or_create_project("/test")
    log_tool_usage(db, project_id, "recall", "query=auth", result_empty=False)

    rows = db.execute(
        "SELECT * FROM tool_usage WHERE project_id = ?", (project_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "recall"
    assert rows[0]["args_summary"] == "query=auth"
    assert rows[0]["result_empty"] == 0


def test_log_tool_usage_truncates_long_args(db):
    project_id = db.get_or_create_project("/test")
    long_args = "x" * 500
    log_tool_usage(db, project_id, "recall", long_args, result_empty=False)

    row = db.execute("SELECT args_summary FROM tool_usage WHERE project_id = ?", (project_id,)).fetchone()
    assert len(row["args_summary"]) <= 200


def test_get_usage_stats_empty(db):
    project_id = db.get_or_create_project("/test")
    stats = get_usage_stats(db, project_id, days=7)
    assert stats == {}


def test_get_usage_stats_counts_correctly(db):
    project_id = db.get_or_create_project("/test")
    now = time.time()

    log_tool_usage(db, project_id, "recall", "q=auth", result_empty=False)
    log_tool_usage(db, project_id, "recall", "q=user", result_empty=True)
    log_tool_usage(db, project_id, "query_symbols", "name=login", result_empty=False)

    stats = get_usage_stats(db, project_id, days=7)
    assert stats["recall"]["total"] == 2
    assert stats["recall"]["empty"] == 1
    assert stats["query_symbols"]["total"] == 1
    assert stats["query_symbols"]["empty"] == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usage_logger.py -v`
Expected: FAIL — module not found

**Step 3: Write minimal implementation**

Create `src/code_memory/usage_logger.py`:

```python
from __future__ import annotations

import time

from src.code_memory.db import Database

_MAX_ARGS_LENGTH = 200


def log_tool_usage(
    db: Database,
    project_id: int,
    tool_name: str,
    args_summary: str,
    result_empty: bool,
) -> None:
    truncated = args_summary[:_MAX_ARGS_LENGTH] if args_summary else ""
    db.execute(
        """INSERT INTO tool_usage (tool_name, project_id, timestamp, args_summary, result_empty)
           VALUES (?, ?, ?, ?, ?)""",
        (tool_name, project_id, time.time(), truncated, result_empty),
    )
    db.conn.commit()


def get_usage_stats(db: Database, project_id: int, days: int = 7) -> dict:
    cutoff = time.time() - (days * 86400)
    rows = db.execute(
        """SELECT tool_name,
                  COUNT(*) as total,
                  SUM(CASE WHEN result_empty THEN 1 ELSE 0 END) as empty
           FROM tool_usage
           WHERE project_id = ? AND timestamp >= ?
           GROUP BY tool_name
           ORDER BY total DESC""",
        (project_id, cutoff),
    ).fetchall()

    return {row["tool_name"]: {"total": row["total"], "empty": row["empty"]} for row in rows}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_usage_logger.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/code_memory/usage_logger.py tests/test_usage_logger.py
git commit -m "feat: add usage logging functions"
```

---

### Task 3: Wire usage logging into MCP tools

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: `tests/test_usage_logging_integration.py`

**Step 1: Write the failing test**

Create `tests/test_usage_logging_integration.py`:

```python
import os
import subprocess

import pytest

from src.code_memory.db import Database, default_db_path
from src.code_memory.mcp_tools import recall, remember, get_project_summary, query_symbols


@pytest.fixture
def project_env(tmp_path, monkeypatch):
    """Set up a git repo and point mcp_tools at it."""
    import src.code_memory.mcp_tools as mt

    # Reset global state
    mt._manager = None
    mt._graph = None

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    subprocess.run(["git", "init"], cwd=project_dir, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=project_dir, capture_output=True)

    monkeypatch.chdir(project_dir)

    yield project_dir

    mt._manager = None
    mt._graph = None


def test_remember_logs_usage(project_env):
    result = remember(notes="test note")
    assert "Stored memory" in result

    db_path = default_db_path(str(project_env))
    db = Database(db_path)
    db.initialize()
    rows = db.execute("SELECT * FROM tool_usage WHERE tool_name = 'remember'").fetchall()
    assert len(rows) == 1
    assert rows[0]["result_empty"] == 0


def test_recall_logs_usage_with_empty_flag(project_env):
    result = recall(query="nonexistent")
    assert "No memories found" in result

    db_path = default_db_path(str(project_env))
    db = Database(db_path)
    db.initialize()
    rows = db.execute("SELECT * FROM tool_usage WHERE tool_name = 'recall'").fetchall()
    assert len(rows) == 1
    assert rows[0]["result_empty"] == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usage_logging_integration.py -v`
Expected: FAIL — no rows in tool_usage (logging not wired in yet)

**Step 3: Add logging calls to each tool in mcp_tools.py**

At the top of `src/code_memory/mcp_tools.py`, add import:

```python
from src.code_memory.usage_logger import log_tool_usage
```

Then add logging calls at the end of each tool function, just before the return. For each tool:

**`remember`** — after line 81:
```python
    log_tool_usage(manager.db, manager.project_id, "remember", f"notes={notes[:50]}", result_empty=False)
```

**`recall`** — after building results (line 112), before return:
```python
    log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=not results)
```
(Move the early return `if not results` after logging, or add logging before it.)

**`get_project_summary`** — before return:
```python
    log_tool_usage(manager.db, manager.project_id, "get_project_summary", "", result_empty=False)
```

**`forget`** — before each return:
```python
    log_tool_usage(manager.db, manager.project_id, "forget", f"id={memory_id}", result_empty=not found)
```

**`index_project`** — before each return:
```python
    log_tool_usage(manager.db, manager.project_id, "index_project", "", result_empty=False)
```

**`query_symbols`** — before return:
```python
    log_tool_usage(manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=not results)
```

**`get_dependencies`** — before return:
```python
    log_tool_usage(manager.db, manager.project_id, "get_dependencies", f"symbol={symbol_name}", result_empty=not deps)
```

**`get_callers`** — before return:
```python
    log_tool_usage(manager.db, manager.project_id, "get_callers", f"symbol={symbol_name}", result_empty=not callers)
```

**`trace_call_chain`** — before return:
```python
    log_tool_usage(manager.db, manager.project_id, "trace_call_chain", f"from={from_symbol} to={to_symbol}", result_empty=not chains)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_usage_logging_integration.py -v`
Expected: ALL PASS

Run: `uv run pytest -v`
Expected: ALL PASS (no regressions)

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_usage_logging_integration.py
git commit -m "feat: wire usage logging into all MCP tools"
```

---

### Task 4: Add `get_usage_stats` MCP tool

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: `tests/test_usage_logging_integration.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_usage_logging_integration.py`:

```python
from src.code_memory.mcp_tools import get_usage_stats as mcp_get_usage_stats


def test_get_usage_stats_tool(project_env):
    remember(notes="test note")
    recall(query="nonexistent")
    recall(query="also nonexistent")

    result = mcp_get_usage_stats(days=7)
    assert "recall" in result
    assert "2 calls" in result
    assert "remember" in result
    assert "1 call" in result
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usage_logging_integration.py::test_get_usage_stats_tool -v`
Expected: FAIL — cannot import `get_usage_stats`

**Step 3: Add the MCP tool to mcp_tools.py**

```python
@mcp.tool(
    name="get_usage_stats",
    title="Usage Stats",
    description=(
        "Use to check how often code-memory tools are being used."
        " Shows call counts and empty-result rates per tool."
    ),
)
def get_usage_stats(days: int = 7) -> str:
    """Show usage statistics for code-memory tools.

    Args:
        days: Number of days to look back (default 7)
    """
    from src.code_memory.usage_logger import get_usage_stats as _get_stats

    manager = _get_manager()
    stats = _get_stats(manager.db, manager.project_id, days)
    if not stats:
        return f"No tool usage recorded in the last {days} days."

    lines = [f"Last {days} days:"]
    for tool_name, counts in stats.items():
        empty_str = f" ({counts['empty']} empty)" if counts["empty"] else ""
        call_word = "call" if counts["total"] == 1 else "calls"
        lines.append(f"  {tool_name}: {counts['total']} {call_word}{empty_str}")
    return "\n".join(lines)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_usage_logging_integration.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_usage_logging_integration.py
git commit -m "feat: add get_usage_stats MCP tool"
```

---

### Task 5: Enhance empty-result responses with bootstrap guidance

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: `tests/test_usage_logging_integration.py` (extend)

**Step 1: Write the failing test**

Add to `tests/test_usage_logging_integration.py`:

```python
def test_recall_empty_suggests_indexing(project_env):
    result = recall(query="nonexistent")
    assert "index_project" in result.lower() or "index" in result.lower()


def test_get_project_summary_suggests_indexing_when_no_index(project_env):
    result = get_project_summary()
    assert "index" in result.lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_usage_logging_integration.py::test_recall_empty_suggests_indexing tests/test_usage_logging_integration.py::test_get_project_summary_suggests_indexing_when_no_index -v`
Expected: FAIL — current messages don't mention indexing

**Step 3: Enhance the tool responses**

In `src/code_memory/mcp_tools.py`:

**`recall`** — change the "No memories found" return:
```python
    if not results:
        log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=True)
        return "No memories found. Use remember() to store context, or run index_project then try query_symbols."
```

**`get_project_summary`** — after building the lines list, before the final return, check index status:
```python
    # Check if index is populated
    symbol_count = manager.db.execute(
        "SELECT COUNT(*) FROM symbols WHERE project_id = ?",
        (manager.project_id,),
    ).fetchone()[0]
    last_commit = manager.db.get_last_indexed_commit(manager.project_id)

    if symbol_count == 0:
        lines.append("")
        lines.append("Symbol index is empty. Run index_project to populate it.")
    elif not last_commit:
        lines.append("")
        lines.append("Symbol index may be stale. Run index_project to refresh.")
```

**`get_dependencies`** — change "No dependencies found" return:
```python
    if not deps:
        return f"No dependencies found for '{symbol_name}'. The index may be empty — try running index_project first."
```

**`get_callers`** — change "No callers found" return:
```python
    if not callers:
        return f"No callers found for '{symbol_name}'. The index may be empty — try running index_project first."
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_usage_logging_integration.py -v`
Expected: ALL PASS

Run: `uv run pytest -v`
Expected: ALL PASS (check no regressions in existing tests)

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_usage_logging_integration.py
git commit -m "feat: enhance empty-result responses with bootstrap guidance"
```

---

### Task 6: Rewrite memory-usage skill with stronger nudges

**Files:**
- Modify: `skills/memory-usage/SKILL.md`

**Step 1: Rewrite the skill**

Replace the content of `skills/memory-usage/SKILL.md` with:

```markdown
---
name: memory-usage
description: "IMPORTANT: Before searching code, reading files, or exploring the codebase, use code-memory MCP tools (recall, query_symbols, get_dependencies, get_project_summary) for persistent context. These tools replace Grep/Glob/Read for understanding code structure."
---

## Code Memory — Mandatory Usage

You have persistent memory and symbol indexing via the code-memory MCP server. You MUST use these tools before falling back to Grep/Glob/Read.

### Session Start (REQUIRED)

Every session, before doing anything else:
1. Call `get_project_summary` to load existing memories
2. If the response says the index is empty or stale, call `index_project`
3. If the user's request relates to existing code, call `recall` with the topic

### Decision Tree for Code Exploration

**Need to find a function, class, or method?**
→ MUST use `query_symbols("name")` first. Only use Grep if query_symbols returns no results.

**Need to understand what a function depends on?**
→ MUST use `get_dependencies("symbol_name")`. Only read the file if you need implementation details beyond the signature.

**Need to know who calls a function?**
→ MUST use `get_callers("symbol_name")`. Do not grep for the function name.

**Need context about code you or a previous session explored?**
→ MUST use `recall("topic")` first. Only search files if recall returns nothing.

**Need to read actual file contents?**
→ This is fine — use Read. But only AFTER checking query_symbols/recall first.

### Storing Context (REQUIRED)

When you discover something important about the code:
- Call `remember` with concise notes focused on "why" and "how"
- Link to specific files and symbols for better recall
- Check with `recall` first to avoid duplicates

### What NOT to Do

- Do NOT use Grep to find function definitions — use `query_symbols`
- Do NOT use Grep to find callers — use `get_callers`
- Do NOT skip `recall` when starting work on a topic you may have seen before
- Do NOT ignore the session-start checklist
```

**Step 2: Review the changes visually — no automated test for skill text**

Read the file to confirm it saved correctly.

**Step 3: Commit**

```bash
git add skills/memory-usage/SKILL.md
git commit -m "docs: rewrite memory-usage skill with mandatory language"
```

---

### Task 7: Update README with new tool

**Files:**
- Modify: `README.md`

**Step 1: Add `get_usage_stats` to the tools table**

In the Tools section of `README.md`, add a row to the table:

```markdown
| `get_usage_stats(days?)` | Show how often code-memory tools are called. Helps monitor adoption. |
```

Update the tool count from "9 MCP tools" to "10 MCP tools".

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add get_usage_stats to README tools table"
```

---

### Task 8: Run full test suite and verify

**Step 1: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

**Step 2: Verify the MCP server starts**

Run: `uv run python -m src.code_memory --help` or start the server briefly to confirm no import errors.

**Step 3: Final commit if any fixups needed**

Only if tests revealed issues that needed fixing.