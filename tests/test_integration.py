"""End-to-end test: memory lifecycle through the manager layer."""

import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.memory_manager import MemoryManager


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

    # Create a small Python project
    (tmp_path / "auth.py").write_text(
        "def login(user, password):\n    return validate(user, password)\n"
    )
    (tmp_path / "utils.py").write_text(
        "def validate(user, password):\n    return user == 'admin'\n"
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
def manager(git_project, tmp_path):
    db = Database(str(tmp_path / "integration.db"))
    db.initialize()
    mgr = MemoryManager(db, str(git_project))
    yield mgr
    db.close()


def test_full_memory_lifecycle(manager, git_project):
    # Session 1: explore and remember
    manager.remember(
        file_path="auth.py",
        symbol_name="login",
        notes="authenticates via validate(), no hashing",
    )
    manager.remember(
        file_path="utils.py",
        symbol_name="validate",
        notes="hardcoded admin check — needs refactoring",
    )

    # Session 2: recall
    auth_memories = manager.recall("login")
    assert len(auth_memories) == 1
    assert "validate()" in auth_memories[0]["notes"]
    assert auth_memories[0]["is_stale"] is False

    # Code changes
    (git_project / "auth.py").write_text(
        "def login(user, password):\n    return check_credentials(user, password)\n"
    )
    subprocess.run(["git", "add", "."], cwd=git_project, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "refactor auth"],
        cwd=git_project,
        check=True,
        capture_output=True,
    )

    # Session 3: recall detects staleness
    auth_memories = manager.recall("login")
    assert auth_memories[0]["is_stale"] is True

    # Update memory
    manager.forget(auth_memories[0]["id"])
    manager.remember(
        file_path="auth.py",
        symbol_name="login",
        notes="now uses check_credentials()",
    )

    # Verify updated
    updated = manager.recall("login")
    assert len(updated) == 1
    assert updated[0]["is_stale"] is False
    assert "check_credentials" in updated[0]["notes"]


def test_project_summary_reflects_state(manager):
    summary = manager.get_project_summary()
    assert summary["total_memories"] == 0

    manager.remember(file_path="auth.py", notes="auth module")
    summary = manager.get_project_summary()
    assert summary["total_memories"] == 1
    assert len(summary["recent_memories"]) == 1
