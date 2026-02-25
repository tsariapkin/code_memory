import pytest

from src.code_memory.db import Database
from src.code_memory.usage_logger import get_usage_stats, log_tool_usage


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

    rows = db.execute("SELECT * FROM tool_usage WHERE project_id = ?", (project_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["tool_name"] == "recall"
    assert rows[0]["args_summary"] == "query=auth"
    assert rows[0]["result_empty"] == 0


def test_log_tool_usage_truncates_long_args(db):
    project_id = db.get_or_create_project("/test")
    long_args = "x" * 500
    log_tool_usage(db, project_id, "recall", long_args, result_empty=False)

    row = db.execute(
        "SELECT args_summary FROM tool_usage WHERE project_id = ?", (project_id,)
    ).fetchone()
    assert len(row["args_summary"]) <= 200


def test_get_usage_stats_empty(db):
    project_id = db.get_or_create_project("/test")
    stats = get_usage_stats(db, project_id, days=7)
    assert stats == {}


def test_get_usage_stats_counts_correctly(db):
    project_id = db.get_or_create_project("/test")

    log_tool_usage(db, project_id, "recall", "q=auth", result_empty=False)
    log_tool_usage(db, project_id, "recall", "q=user", result_empty=True)
    log_tool_usage(db, project_id, "query_symbols", "name=login", result_empty=False)

    stats = get_usage_stats(db, project_id, days=7)
    assert stats["recall"]["total"] == 2
    assert stats["recall"]["empty"] == 1
    assert stats["query_symbols"]["total"] == 1
    assert stats["query_symbols"]["empty"] == 0
