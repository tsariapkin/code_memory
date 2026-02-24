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
    (tmp_path / "src" / "base.py").write_text("class Animal:\n    def speak(self):\n        pass\n")
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


def _has_node_with_symbol(graph, symbol_name):
    """Check if the graph has any node with the given symbol_name attribute."""
    return any(d.get("symbol_name") == symbol_name for _, d in graph.graph.nodes(data=True))


def test_build_from_db_loads_nodes(graph, indexed_project):
    db, project_id = indexed_project
    graph.build_from_db(db, project_id)
    assert len(graph.graph.nodes) > 0
    assert _has_node_with_symbol(graph, "bark")
    assert _has_node_with_symbol(graph, "main")


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
