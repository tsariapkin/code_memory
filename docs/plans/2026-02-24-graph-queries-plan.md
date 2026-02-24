# Graph Query Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an in-memory NetworkX graph engine over SQLite for reverse traversal, multi-hop path finding, and richer relationship types (inheritance, imports).

**Architecture:** SQLite stays as the single persistence layer. NetworkX DiGraph is built from SQLite on demand and provides traversal queries. Two new MCP tools (`get_callers`, `trace_call_chain`) expose graph capabilities.

**Tech Stack:** Python 3.10+, NetworkX, SQLite, tree-sitter, mcp[cli]

**Design doc:** `docs/plans/2026-02-24-graph-queries-design.md`

---

### Task 1: Add `networkx` dependency

**Files:**
- Modify: `pyproject.toml:6-10`

**Step 1: Add networkx to dependencies**

In `pyproject.toml`, add `"networkx>=3.0"` to the `dependencies` list:

```toml
dependencies = [
    "mcp[cli]>=1.0.0",
    "tree-sitter>=0.21.0",
    "tree-sitter-python>=0.21.0",
    "networkx>=3.0",
]
```

**Step 2: Install**

Run: `uv sync`
Expected: Resolves and installs networkx

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add networkx for graph query engine"
```

---

### Task 2: Add `language` column and `dep_type` index to DB schema

**Files:**
- Modify: `src/code_memory/db.py:28-49`
- Test: `tests/test_db.py`

**Step 1: Write the failing test**

Add to `tests/test_db.py`:

```python
def test_symbols_table_has_language_column(db):
    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO symbols
           (project_id, file_path, symbol_name, symbol_type, language)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, "test.py", "foo", "function", "python"),
    )
    db.conn.commit()
    row = db.execute(
        "SELECT language FROM symbols WHERE symbol_name = 'foo'"
    ).fetchone()
    assert row["language"] == "python"


def test_symbols_language_defaults_to_python(db):
    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO symbols
           (project_id, file_path, symbol_name, symbol_type)
           VALUES (?, ?, ?, ?)""",
        (project_id, "test.py", "bar", "function"),
    )
    db.conn.commit()
    row = db.execute(
        "SELECT language FROM symbols WHERE symbol_name = 'bar'"
    ).fetchone()
    assert row["language"] == "python"


def test_dependencies_dep_type_index_exists(db):
    indexes = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_deps_type'"
    ).fetchall()
    assert len(indexes) == 1
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::test_symbols_table_has_language_column tests/test_db.py::test_symbols_language_defaults_to_python tests/test_db.py::test_dependencies_dep_type_index_exists -v`
Expected: FAIL — column `language` doesn't exist, index doesn't exist

**Step 3: Update schema in `db.py`**

In `src/code_memory/db.py`, update the `symbols` CREATE TABLE to add `language`:

```sql
CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    language TEXT DEFAULT 'python',
    line_start INTEGER,
    line_end INTEGER,
    signature TEXT,
    content_hash TEXT,
    UNIQUE(project_id, file_path, symbol_name)
);
```

And add the dep_type index after the existing indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_deps_type ON dependencies(dep_type);
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All PASS

**Step 5: Run full test suite to verify no regressions**

Run: `uv run pytest -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add src/code_memory/db.py tests/test_db.py
git commit -m "feat: add language column to symbols and dep_type index"
```

---

### Task 3: Extract class inheritance from tree-sitter AST

**Files:**
- Modify: `src/code_memory/symbol_indexer.py:97-128`
- Test: `tests/test_symbol_indexer.py`

**Step 1: Write the failing test**

Add to `tests/test_symbol_indexer.py`:

```python
INHERITANCE_CODE = '''\
class Base:
    pass


class Mixin:
    pass


class Child(Base, Mixin):
    def do_thing(self):
        pass
'''


def test_parse_extracts_base_classes(tmp_path):
    f = tmp_path / "inherit.py"
    f.write_text(INHERITANCE_CODE)
    symbols = parse_file_symbols(str(f))

    child = next(s for s in symbols if s["symbol_name"] == "Child")
    assert child["base_classes"] == ["Base", "Mixin"]


def test_parse_no_base_classes_when_none(tmp_path):
    f = tmp_path / "inherit.py"
    f.write_text(INHERITANCE_CODE)
    symbols = parse_file_symbols(str(f))

    base = next(s for s in symbols if s["symbol_name"] == "Base")
    assert base["base_classes"] == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_symbol_indexer.py::test_parse_extracts_base_classes tests/test_symbol_indexer.py::test_parse_no_base_classes_when_none -v`
Expected: FAIL — KeyError `base_classes`

**Step 3: Add base class extraction to `parse_file_symbols`**

In `src/code_memory/symbol_indexer.py`, in the `class_definition` branch (~line 97), extract superclasses from the `argument_list` node:

```python
elif child.type == "class_definition":
    class_name_node = child.child_by_field_name("name")
    class_name = class_name_node.text.decode("utf-8")

    # Extract base classes from superclasses node
    base_classes = []
    superclasses = child.child_by_field_name("superclasses")
    if superclasses:
        for arg in superclasses.named_children:
            if arg.type == "identifier":
                base_classes.append(arg.text.decode("utf-8"))
            elif arg.type == "attribute":
                base_classes.append(arg.text.decode("utf-8"))

    symbols.append(
        {
            "symbol_name": class_name,
            "symbol_type": "class",
            "line_start": child.start_point[0] + 1,
            "line_end": child.end_point[0] + 1,
            "signature": _extract_signature(child),
            "content_hash": _content_hash(child.text),
            "base_classes": base_classes,
        }
    )
```

Also add `"base_classes": []` to function, method, and import symbol dicts so the field is always present.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_symbol_indexer.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/code_memory/symbol_indexer.py tests/test_symbol_indexer.py
git commit -m "feat: extract base classes from class definitions"
```

---

### Task 4: Extract inheritance and import edges in `extract_dependencies`

**Files:**
- Modify: `src/code_memory/symbol_indexer.py:363-417`
- Test: `tests/test_dependencies.py`

**Step 1: Write the failing tests**

Add to `tests/test_dependencies.py`:

```python
def test_extract_dependencies_finds_inheritance(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "class Base:\n    pass\n\n\nclass Child(Base):\n    pass\n"
    )
    deps = extract_dependencies(str(code_file))
    inherits = [d for d in deps if d["dep_type"] == "inherits"]
    assert len(inherits) == 1
    assert inherits[0]["source"] == "Child"
    assert inherits[0]["target"] == "Base"


def test_extract_dependencies_finds_multiple_inheritance(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "class A:\n    pass\n\nclass B:\n    pass\n\nclass C(A, B):\n    pass\n"
    )
    deps = extract_dependencies(str(code_file))
    inherits = [d for d in deps if d["dep_type"] == "inherits"]
    targets = [d["target"] for d in inherits]
    assert "A" in targets
    assert "B" in targets


def test_extract_dependencies_finds_import_edges(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "from pathlib import Path\nimport os\n\ndef read_file(name):\n    return Path(name).read_text()\n"
    )
    deps = extract_dependencies(str(code_file))
    import_deps = [d for d in deps if d["dep_type"] == "imports"]
    # read_file imports Path (used in body)
    assert any(d["source"] == "read_file" and d["target"] == "Path" for d in import_deps)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dependencies.py::test_extract_dependencies_finds_inheritance tests/test_dependencies.py::test_extract_dependencies_finds_multiple_inheritance tests/test_dependencies.py::test_extract_dependencies_finds_import_edges -v`
Expected: FAIL — no `inherits` or `imports` dep_type in results

**Step 3: Add inheritance and import edge extraction to `extract_dependencies`**

In `src/code_memory/symbol_indexer.py`, modify `extract_dependencies`:

After collecting `func_ranges`, also collect class inheritance info:

```python
# Collect class inheritance
class_bases = []
for child in root.children:
    if child.type == "class_definition":
        class_name = child.child_by_field_name("name").text.decode("utf-8")
        superclasses = child.child_by_field_name("superclasses")
        if superclasses:
            for arg in superclasses.named_children:
                if arg.type in ("identifier", "attribute"):
                    base_name = arg.text.decode("utf-8")
                    class_bases.append(("inherits", class_name, base_name))

# Collect import names for matching
import_names = set()
for child in root.children:
    if child.type in ("import_statement", "import_from_statement"):
        for named_child in child.named_children:
            if named_child.type == "dotted_name":
                import_names.add(named_child.text.decode("utf-8"))
            elif named_child.type == "aliased_import":
                name = named_child.child_by_field_name("name")
                if name:
                    import_names.add(name.text.decode("utf-8"))
```

Then after building `deps` from calls, append inheritance edges:

```python
for dep_type, source, target in class_bases:
    key = (source, target)
    if key not in seen:
        seen.add(key)
        deps.append({"source": source, "target": target, "dep_type": dep_type})
```

And for import edges — for each call that matches an import name, add an `"imports"` edge from the enclosing function to the imported name:

```python
for call_name, call_line in calls:
    if call_name in import_names:
        enclosing = _find_enclosing_func(call_line, func_ranges)
        if enclosing:
            key = (enclosing, call_name, "imports")
            if key not in seen:
                seen.add(key)
                deps.append({"source": enclosing, "target": call_name, "dep_type": "imports"})
```

Note: update the `seen` set to use 3-tuples `(source, target, dep_type)` to allow both a `calls` and `imports` edge between the same pair.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_dependencies.py -v`
Expected: All PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass — existing `"calls"` extraction unchanged

**Step 6: Commit**

```bash
git add src/code_memory/symbol_indexer.py tests/test_dependencies.py
git commit -m "feat: extract inheritance and import edges in dependency analysis"
```

---

### Task 5: Create `graph_engine.py` — CodeGraph class

**Files:**
- Create: `src/code_memory/graph_engine.py`
- Test: `tests/test_graph_engine.py`

**Step 1: Write the failing tests**

Create `tests/test_graph_engine.py`:

```python
import pytest

from src.code_memory.db import Database
from src.code_memory.graph_engine import CodeGraph
from src.code_memory.symbol_indexer import index_project_files


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def graph():
    return CodeGraph()


@pytest.fixture
def indexed_project(tmp_path, db):
    """A project with calls, inheritance, and imports indexed into SQLite."""
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "base.py").write_text(
        "class Animal:\n    def speak(self):\n        pass\n"
    )
    (tmp_path / "src" / "dog.py").write_text(
        "from base import Animal\n\n\n"
        "class Dog(Animal):\n    def speak(self):\n        return bark()\n\n\n"
        "def bark():\n    return 'woof'\n"
    )
    (tmp_path / "src" / "app.py").write_text(
        "from dog import Dog\n\n\n"
        "def main():\n    d = Dog()\n    d.speak()\n    greet()\n\n\n"
        "def greet():\n    return 'hello'\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    index_project_files(db, project_id, str(tmp_path))
    return db, project_id


def test_build_from_db_loads_nodes(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    assert len(graph.graph.nodes) > 0
    assert "bark" in graph.graph.nodes
    assert "main" in graph.graph.nodes


def test_build_from_db_loads_edges(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    assert len(graph.graph.edges) > 0


def test_get_dependencies(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    deps = graph.get_dependencies("main")
    dep_names = [d["symbol_name"] for d in deps]
    assert "greet" in dep_names


def test_get_callers(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    callers = graph.get_callers("greet")
    caller_names = [c["symbol_name"] for c in callers]
    assert "main" in caller_names


def test_get_callers_no_results(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    callers = graph.get_callers("main")
    assert callers == []


def test_trace_call_chain(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    chains = graph.trace_call_chain("main", "greet", max_depth=3)
    assert len(chains) >= 1
    assert chains[0][0] == "main"
    assert chains[0][-1] == "greet"


def test_trace_call_chain_no_path(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    chains = graph.trace_call_chain("greet", "main", max_depth=5)
    assert chains == []


def test_invalidate_clears_graph(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    assert len(graph.graph.nodes) > 0
    graph.invalidate()
    assert len(graph.graph.nodes) == 0
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph_engine.py -v`
Expected: FAIL — ModuleNotFoundError for `graph_engine`

**Step 3: Implement `graph_engine.py`**

Create `src/code_memory/graph_engine.py`:

```python
from __future__ import annotations

import networkx as nx


class CodeGraph:
    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._loaded = False

    def build_from_db(self, db, project_id: int) -> None:
        """Load symbols as nodes and dependencies as edges from SQLite."""
        self.graph.clear()

        # Load nodes
        rows = db.execute(
            """SELECT id, symbol_name, symbol_type, file_path,
                      line_start, line_end, signature
               FROM symbols WHERE project_id = ?""",
            (project_id,),
        ).fetchall()

        id_to_name = {}
        for row in rows:
            row = dict(row)
            name = row["symbol_name"]
            id_to_name[row["id"]] = name
            self.graph.add_node(
                name,
                symbol_type=row["symbol_type"],
                file_path=row["file_path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                signature=row["signature"],
            )

        # Load edges
        deps = db.execute(
            """SELECT d.source_id, d.target_id, d.dep_type
               FROM dependencies d
               JOIN symbols s ON d.source_id = s.id
               WHERE s.project_id = ?""",
            (project_id,),
        ).fetchall()

        for dep in deps:
            dep = dict(dep)
            source = id_to_name.get(dep["source_id"])
            target = id_to_name.get(dep["target_id"])
            if source and target:
                self.graph.add_edge(source, target, dep_type=dep["dep_type"])

        self._loaded = True

    def get_dependencies(self, symbol_name: str) -> list[dict]:
        """Forward traversal — what does this symbol call/import/inherit?"""
        if symbol_name not in self.graph:
            return []
        results = []
        for _, target, data in self.graph.out_edges(symbol_name, data=True):
            node = self.graph.nodes[target]
            results.append(
                {
                    "symbol_name": target,
                    "symbol_type": node.get("symbol_type", ""),
                    "file_path": node.get("file_path", ""),
                    "signature": node.get("signature", ""),
                    "dep_type": data.get("dep_type", ""),
                }
            )
        return results

    def get_callers(self, symbol_name: str) -> list[dict]:
        """Reverse traversal — who calls/imports this symbol?"""
        if symbol_name not in self.graph:
            return []
        results = []
        for source, _, data in self.graph.in_edges(symbol_name, data=True):
            node = self.graph.nodes[source]
            results.append(
                {
                    "symbol_name": source,
                    "symbol_type": node.get("symbol_type", ""),
                    "file_path": node.get("file_path", ""),
                    "signature": node.get("signature", ""),
                    "dep_type": data.get("dep_type", ""),
                }
            )
        return results

    def trace_call_chain(
        self, from_symbol: str, to_symbol: str, max_depth: int = 5
    ) -> list[list[str]]:
        """Find all simple paths between two symbols up to max_depth."""
        if from_symbol not in self.graph or to_symbol not in self.graph:
            return []
        try:
            paths = list(
                nx.all_simple_paths(
                    self.graph, from_symbol, to_symbol, cutoff=max_depth
                )
            )
        except nx.NetworkXError:
            return []
        return paths

    def invalidate(self) -> None:
        """Clear the graph to force rebuild on next query."""
        self.graph.clear()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph_engine.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/code_memory/graph_engine.py tests/test_graph_engine.py
git commit -m "feat: add CodeGraph engine with NetworkX for graph traversal"
```

---

### Task 6: Wire CodeGraph into `mcp_tools.py` — update existing tools

**Files:**
- Modify: `src/code_memory/mcp_tools.py`

**Step 1: Add graph initialization**

In `mcp_tools.py`, add a module-level `_graph` variable and update `_get_manager()` to also create and store a `CodeGraph`:

```python
from src.code_memory.graph_engine import CodeGraph

_graph: CodeGraph | None = None


def _get_graph() -> CodeGraph:
    global _graph
    if _graph is None:
        _graph = CodeGraph()
    return _graph


def _ensure_graph_loaded() -> CodeGraph:
    graph = _get_graph()
    if not graph.is_loaded:
        manager = _get_manager()
        graph.build_from_db(manager.db, manager.project_id)
    return graph
```

**Step 2: Update `get_dependencies` tool to use CodeGraph**

Replace the body of `get_dependencies()`:

```python
@mcp.tool()
def get_dependencies(symbol_name: str) -> str:
    """List what a symbol depends on (calls, imports, inherits).

    Helps understand code flow without reading entire files.

    Args:
        symbol_name: Exact symbol name (e.g. "login", "UserService.get_user")
    """
    graph = _ensure_graph_loaded()
    deps = graph.get_dependencies(symbol_name)
    if not deps:
        return f"No dependencies found for '{symbol_name}'."

    lines = [f"Dependencies of {symbol_name}:"]
    for d in deps:
        lines.append(
            f"  {d['dep_type']} {d['symbol_name']} ({d['symbol_type']}) in {d['file_path']}"
        )
        if d.get("signature"):
            lines.append(f"    {d['signature']}")
    return "\n".join(lines)
```

**Step 3: Update `index_project` to invalidate graph**

At the end of `index_project()`, before the return statements, add:

```python
_get_graph().invalidate()
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py
git commit -m "refactor: wire CodeGraph into existing MCP tools"
```

---

### Task 7: Add `get_callers` MCP tool

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: `tests/test_phase2_integration.py` (or create `tests/test_graph_tools.py`)

**Step 1: Write the failing test**

Create `tests/test_graph_tools.py`:

```python
import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.graph_engine import CodeGraph
from src.code_memory.symbol_indexer import index_project_files


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def graph():
    return CodeGraph()


@pytest.fixture
def project_with_calls(tmp_path, db):
    (tmp_path / "app.py").write_text(
        "def main():\n    result = process()\n    return format_output(result)\n\n\n"
        "def process():\n    data = fetch()\n    return transform(data)\n\n\n"
        "def fetch():\n    return [1, 2, 3]\n\n\n"
        "def transform(data):\n    return [x * 2 for x in data]\n\n\n"
        "def format_output(result):\n    return str(result)\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    index_project_files(db, project_id, str(tmp_path))
    return db, project_id


def test_get_callers_finds_reverse_deps(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    callers = graph.get_callers("process")
    caller_names = [c["symbol_name"] for c in callers]
    assert "main" in caller_names


def test_get_callers_returns_empty_for_root(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    callers = graph.get_callers("main")
    assert callers == []


def test_get_callers_unknown_symbol(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    callers = graph.get_callers("nonexistent")
    assert callers == []
```

**Step 2: Run tests to verify they pass (graph_engine tests)**

Run: `uv run pytest tests/test_graph_tools.py -v`
Expected: PASS (these test CodeGraph directly, which already works)

**Step 3: Add `get_callers` MCP tool**

In `src/code_memory/mcp_tools.py`, add:

```python
@mcp.tool()
def get_callers(symbol_name: str) -> str:
    """List what calls or imports a symbol (reverse dependency lookup).

    Useful for understanding impact of changes — "who will break if I change this?"

    Args:
        symbol_name: Exact symbol name (e.g. "validate", "UserService.login")
    """
    graph = _ensure_graph_loaded()
    callers = graph.get_callers(symbol_name)
    if not callers:
        return f"No callers found for '{symbol_name}'."

    lines = [f"Callers of {symbol_name}:"]
    for c in callers:
        lines.append(
            f"  {c['dep_type']} from {c['symbol_name']} ({c['symbol_type']}) in {c['file_path']}"
        )
        if c.get("signature"):
            lines.append(f"    {c['signature']}")
    return "\n".join(lines)
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_graph_tools.py
git commit -m "feat: add get_callers MCP tool for reverse dependency lookup"
```

---

### Task 8: Add `trace_call_chain` MCP tool

**Files:**
- Modify: `src/code_memory/mcp_tools.py`
- Test: `tests/test_graph_tools.py`

**Step 1: Write the failing test**

Add to `tests/test_graph_tools.py`:

```python
def test_trace_call_chain_finds_path(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    chains = graph.trace_call_chain("main", "fetch", max_depth=5)
    assert len(chains) >= 1
    # main -> process -> fetch
    assert chains[0][0] == "main"
    assert chains[0][-1] == "fetch"


def test_trace_call_chain_no_path(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    chains = graph.trace_call_chain("fetch", "main", max_depth=5)
    assert chains == []


def test_trace_call_chain_respects_max_depth(graph, project_with_calls):
    db, project_id = project_with_calls
    graph.build_from_db(db, project_id)
    # main -> process -> fetch is depth 2, so max_depth=1 shouldn't find it
    chains = graph.trace_call_chain("main", "fetch", max_depth=1)
    assert chains == []
```

**Step 2: Run tests to verify they pass (graph_engine level)**

Run: `uv run pytest tests/test_graph_tools.py -v`
Expected: PASS

**Step 3: Add `trace_call_chain` MCP tool**

In `src/code_memory/mcp_tools.py`, add:

```python
@mcp.tool()
def trace_call_chain(from_symbol: str, to_symbol: str, max_depth: int = 5) -> str:
    """Find call chains between two symbols (multi-hop traversal).

    Shows all paths from one function to another through the call graph.
    Useful for understanding how a request flows from endpoint to database.

    Args:
        from_symbol: Starting symbol name
        to_symbol: Target symbol name
        max_depth: Maximum chain length (default 5)
    """
    graph = _ensure_graph_loaded()
    chains = graph.trace_call_chain(from_symbol, to_symbol, max_depth)
    if not chains:
        return f"No call chain found from '{from_symbol}' to '{to_symbol}' (max depth {max_depth})."

    lines = [f"Call chains from {from_symbol} to {to_symbol}:"]
    for i, chain in enumerate(chains, 1):
        lines.append(f"  {i}. {' -> '.join(chain)}")
    return "\n".join(lines)
```

**Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/code_memory/mcp_tools.py tests/test_graph_tools.py
git commit -m "feat: add trace_call_chain MCP tool for multi-hop traversal"
```

---

### Task 9: Update README and skill docs

**Files:**
- Modify: `README.md`
- Modify: `skills/summary/SKILL.md` (if it lists tools)

**Step 1: Update README tools table**

Update the tools table in `README.md` to include the 2 new tools:

```markdown
| `get_callers(symbol_name)` | Reverse dependency lookup — who calls this symbol? |
| `trace_call_chain(from_symbol, to_symbol, max_depth?)` | Find all call paths between two symbols. |
```

Update the tool count from 7 to 9.

Add a brief section under "Symbol queries" showing usage:

```markdown
### Reverse lookups & call chains

```
get_callers("validate")           # who calls validate?
trace_call_chain("main", "query_db")  # how does main reach query_db?
```
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README with new graph query tools"
```

---

### Task 10: End-to-end integration test

**Files:**
- Test: `tests/test_graph_integration.py`

**Step 1: Write integration test**

Create `tests/test_graph_integration.py`:

```python
"""End-to-end test: index a project, query the graph, verify callers and chains."""

import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.graph_engine import CodeGraph
from src.code_memory.symbol_indexer import index_project_files


@pytest.fixture
def git_project(tmp_path):
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path, check=True, capture_output=True,
    )

    (tmp_path / "models.py").write_text(
        "class BaseModel:\n    def save(self):\n        pass\n\n\n"
        "class User(BaseModel):\n    def validate(self):\n        return check_email(self)\n\n\n"
        "def check_email(user):\n    return '@' in str(user)\n"
    )
    (tmp_path / "views.py").write_text(
        "from models import User\n\n\n"
        "def create_user(data):\n    u = User()\n    u.validate()\n    u.save()\n    return u\n\n\n"
        "def list_users():\n    return []\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    return tmp_path


@pytest.fixture
def setup(git_project, tmp_path):
    db = Database(str(tmp_path / "integration.db"))
    db.initialize()
    project_id = db.get_or_create_project(str(git_project))
    index_project_files(db, project_id, str(git_project))
    graph = CodeGraph()
    graph.build_from_db(db, project_id)
    yield db, project_id, graph
    db.close()


def test_full_graph_workflow(setup):
    db, project_id, graph = setup

    # Forward deps: create_user calls validate, save
    deps = graph.get_dependencies("create_user")
    dep_names = [d["symbol_name"] for d in deps]
    assert "validate" in dep_names or "User" in dep_names

    # Reverse: who calls check_email?
    callers = graph.get_callers("check_email")
    caller_names = [c["symbol_name"] for c in callers]
    assert "User.validate" in caller_names or "validate" in caller_names

    # Graph has nodes from both files
    assert "create_user" in graph.graph.nodes
    assert "list_users" in graph.graph.nodes
    assert "check_email" in graph.graph.nodes


def test_graph_rebuilds_after_invalidate(setup):
    db, project_id, graph = setup
    assert graph.is_loaded
    assert len(graph.graph.nodes) > 0

    graph.invalidate()
    assert not graph.is_loaded
    assert len(graph.graph.nodes) == 0

    graph.build_from_db(db, project_id)
    assert graph.is_loaded
    assert len(graph.graph.nodes) > 0
```

**Step 2: Run integration test**

Run: `uv run pytest tests/test_graph_integration.py -v`
Expected: All PASS

**Step 3: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/test_graph_integration.py
git commit -m "test: add end-to-end integration tests for graph query engine"
```
