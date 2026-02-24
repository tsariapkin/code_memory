import pytest

from src.code_memory.db import Database


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


def test_symbols_table_exists(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [row[0] for row in tables]
    assert "symbols" in table_names


def test_dependencies_table_exists(db):
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = [row[0] for row in tables]
    assert "dependencies" in table_names


def test_insert_and_query_symbol(db):
    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO symbols (project_id, file_path, symbol_name, symbol_type,
                                line_start, line_end, signature, content_hash)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            project_id,
            "auth.py",
            "login",
            "function",
            1,
            5,
            "def login(user: str, password: str) -> bool",
            "abc123",
        ),
    )
    db.conn.commit()

    row = db.execute(
        "SELECT * FROM symbols WHERE project_id = ? AND symbol_name = ?",
        (project_id, "login"),
    ).fetchone()
    assert row is not None
    assert row["symbol_type"] == "function"
    assert row["line_start"] == 1
    assert row["line_end"] == 5


def test_insert_dependency(db):
    project_id = db.get_or_create_project("/test")
    db.execute(
        """INSERT INTO symbols (project_id, file_path, symbol_name, symbol_type,
                                line_start, line_end)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, "auth.py", "login", "function", 1, 5),
    )
    db.execute(
        """INSERT INTO symbols (project_id, file_path, symbol_name, symbol_type,
                                line_start, line_end)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, "utils.py", "validate", "function", 1, 3),
    )
    db.conn.commit()

    source_id = db.execute("SELECT id FROM symbols WHERE symbol_name = 'login'").fetchone()[0]
    target_id = db.execute("SELECT id FROM symbols WHERE symbol_name = 'validate'").fetchone()[0]

    db.execute(
        "INSERT INTO dependencies (source_id, target_id, dep_type) VALUES (?, ?, ?)",
        (source_id, target_id, "calls"),
    )
    db.conn.commit()

    deps = db.execute("SELECT * FROM dependencies WHERE source_id = ?", (source_id,)).fetchall()
    assert len(deps) == 1
    assert deps[0]["target_id"] == target_id
    assert deps[0]["dep_type"] == "calls"
