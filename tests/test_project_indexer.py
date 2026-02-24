import pytest

from src.code_memory.db import Database
from src.code_memory.symbol_indexer import (
    index_project_files,
    index_project_symbols,
    query_symbol,
)


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def python_project(tmp_path):
    """A small Python project with two files."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "auth.py").write_text(
        'import hashlib\n\n\ndef login(user: str, password: str) -> bool:\n    """Authenticate user."""\n    return verify(user, password)\n'
    )
    (src / "utils.py").write_text(
        'def verify(user: str, password: str) -> bool:\n    return user == "admin"\n'
    )
    (tmp_path / "README.md").write_text("not python")
    return tmp_path


def test_index_project_finds_all_symbols(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    count = index_project_symbols(db, project_id, str(python_project))
    assert count >= 3  # login, verify, hashlib import

    rows = db.execute(
        "SELECT symbol_name, symbol_type FROM symbols WHERE project_id = ? ORDER BY symbol_name",
        (project_id,),
    ).fetchall()
    names = [r["symbol_name"] for r in rows]
    assert "login" in names
    assert "verify" in names


def test_index_project_is_idempotent(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    count1 = index_project_symbols(db, project_id, str(python_project))
    count2 = index_project_symbols(db, project_id, str(python_project))
    assert count1 == count2

    total = db.execute(
        "SELECT COUNT(*) FROM symbols WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    assert total == count1  # no duplicates


def test_query_symbol_returns_details(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    index_project_symbols(db, project_id, str(python_project))

    results = query_symbol(db, project_id, "login")
    assert len(results) == 1
    assert results[0]["symbol_name"] == "login"
    assert results[0]["symbol_type"] == "function"
    assert results[0]["signature"] is not None
    assert results[0]["file_path"].endswith("auth.py")


def test_query_symbol_partial_match(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    index_project_symbols(db, project_id, str(python_project))

    results = query_symbol(db, project_id, "ver")
    names = [r["symbol_name"] for r in results]
    assert "verify" in names


def test_index_project_files_returns_both_counts(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    sym_count, dep_count = index_project_files(db, project_id, str(python_project))
    assert sym_count >= 3  # login, verify, hashlib import
    assert dep_count >= 1  # login -> verify


def test_index_project_files_is_idempotent(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    sym1, dep1 = index_project_files(db, project_id, str(python_project))
    sym2, dep2 = index_project_files(db, project_id, str(python_project))
    assert sym1 == sym2
    assert dep1 == dep2

    total_syms = db.execute(
        "SELECT COUNT(*) FROM symbols WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    assert total_syms == sym1
