import sqlite3
import struct

import pytest

from src.code_memory.db import Database


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


def test_initialize_creates_tables(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [row[0] for row in tables]
    assert "memories" in table_names
    assert "project" in table_names


def test_get_or_create_project(db):
    project_id = db.get_or_create_project("/some/path")
    assert project_id == 1

    # Same path returns same ID
    same_id = db.get_or_create_project("/some/path")
    assert same_id == project_id


def test_get_or_create_project_different_paths(db):
    id1 = db.get_or_create_project("/path/a")
    id2 = db.get_or_create_project("/path/b")
    assert id1 != id2


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


def test_symbols_table_has_language_column(db):
    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO symbols
           (project_id, file_path, symbol_name, symbol_type, language)
           VALUES (?, ?, ?, ?, ?)""",
        (project_id, "test.py", "foo", "function", "python"),
    )
    db.conn.commit()
    row = db.execute("SELECT language FROM symbols WHERE symbol_name = 'foo'").fetchone()
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
    row = db.execute("SELECT language FROM symbols WHERE symbol_name = 'bar'").fetchone()
    assert row["language"] == "python"


def test_dependencies_dep_type_index_exists(db):
    indexes = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_deps_type'"
    ).fetchall()
    assert len(indexes) == 1


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


def test_embeddings_table_exists(db):
    cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'")
    assert cursor.fetchone() is not None


def test_embeddings_insert_and_query(db):
    project_id = db.get_or_create_project("/test")
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


def test_embeddings_unique_constraint(db):
    project_id = db.get_or_create_project("/test")
    vector = struct.pack("3f", 0.1, 0.2, 0.3)
    db.execute(
        "INSERT INTO embeddings (project_id, source_type, source_id, text, vector) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, "memory", 1, "text1", vector),
    )
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO embeddings (project_id, source_type, source_id, text, vector) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, "memory", 1, "text2", vector),
        )
