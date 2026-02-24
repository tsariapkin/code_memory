import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.symbol_indexer import index_project_files, query_symbol


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


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
    (tmp_path / "auth.py").write_text(
        "def login(user, password):\n    return verify(user, password)\n"
    )
    (tmp_path / "utils.py").write_text('def verify(user, password):\n    return user == "admin"\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def test_incremental_indexes_only_changed_files(db, git_project):
    project_id = db.get_or_create_project(str(git_project))

    # Full index
    sym1, dep1 = index_project_files(db, project_id, str(git_project))
    assert sym1 >= 2  # login, verify

    # Modify one file
    (git_project / "auth.py").write_text(
        "def login_v2(user, password):\n    return verify(user, password)\n"
    )
    subprocess.run(["git", "add", "."], cwd=git_project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "rename"],
        cwd=git_project,
        check=True,
        capture_output=True,
    )

    # Incremental index with only auth.py
    sym2, dep2 = index_project_files(db, project_id, str(git_project), changed_files=["auth.py"])
    assert sym2 >= 1  # login_v2

    # Old symbol gone, new symbol present
    results = query_symbol(db, project_id, "login")
    names = [r["symbol_name"] for r in results]
    assert "login" not in names
    assert "login_v2" in names

    # verify still present (was not in changed_files)
    results = query_symbol(db, project_id, "verify")
    assert len(results) == 1


def test_incremental_handles_deleted_files(db, git_project):
    project_id = db.get_or_create_project(str(git_project))

    # Full index
    index_project_files(db, project_id, str(git_project))

    # Delete a file
    (git_project / "utils.py").unlink()
    subprocess.run(["git", "add", "."], cwd=git_project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "delete utils"],
        cwd=git_project,
        check=True,
        capture_output=True,
    )

    # Incremental with deleted file
    index_project_files(db, project_id, str(git_project), changed_files=["utils.py"])

    # verify symbol should be gone
    results = query_symbol(db, project_id, "verify")
    assert len(results) == 0

    # login should still exist
    results = query_symbol(db, project_id, "login")
    assert len(results) == 1
