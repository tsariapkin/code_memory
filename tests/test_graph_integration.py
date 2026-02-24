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
        cwd=tmp_path,
        check=True,
        capture_output=True,
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
