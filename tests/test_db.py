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
