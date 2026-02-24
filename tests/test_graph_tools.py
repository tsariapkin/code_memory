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
