import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import find_enclosing_symbol


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
        ["git", "config", "user.name", "Test"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / "auth.py").write_text(
        'def login(user, password):\n    """Login logic."""\n    return verify(user, password)\n\n\ndef verify(user, password):\n    return True\n'
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_find_enclosing_symbol_in_function(git_project):
    result = find_enclosing_symbol(str(git_project / "auth.py"), 2)
    assert result == "login"


def test_find_enclosing_symbol_outside_function(git_project):
    # Line 5 is the blank line between functions
    result = find_enclosing_symbol(str(git_project / "auth.py"), 5)
    assert result is None


def test_remember_with_line_resolves_symbol(git_project, tmp_path):
    """When remember is called with file_path and line but no symbol_name,
    it should auto-resolve the enclosing symbol."""
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    manager = MemoryManager(db, str(git_project))

    # Remember with explicit file + line, no symbol
    file_path = "auth.py"
    line = 2  # inside login()
    enclosing = find_enclosing_symbol(str(git_project / file_path), line)

    manager.remember(
        file_path=file_path,
        symbol_name=enclosing,
        notes="login function validates credentials",
    )

    results = manager.recall("login")
    assert len(results) == 1
    assert results[0]["symbol_name"] == "login"
    db.close()
