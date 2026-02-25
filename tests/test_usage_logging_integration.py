import subprocess

import pytest

from src.code_memory.db import Database, default_db_path
from src.code_memory.mcp_tools import recall, remember


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
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"], cwd=project_dir, capture_output=True
    )

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
