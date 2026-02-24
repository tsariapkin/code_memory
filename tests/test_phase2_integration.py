"""End-to-end test: symbol indexing + memory + dependency flow."""

import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import (
    get_symbol_dependencies,
    index_project_files,
    query_symbol,
)


@pytest.fixture
def project(tmp_path):
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

    (tmp_path / "models.py").write_text(
        'class User:\n    def __init__(self, name):\n        self.name = name\n\n    def greet(self):\n        return f"Hi {self.name}"\n'
    )
    (tmp_path / "service.py").write_text(
        "from models import User\n\n\ndef create_user(name):\n    user = User(name)\n    return user.greet()\n"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    database = Database(str(db_path))
    database.initialize()
    yield database
    database.close()


def test_full_phase2_workflow(project, db):
    project_id = db.get_or_create_project(str(project))

    # Step 1: Index the project
    sym_count, dep_count = index_project_files(db, project_id, str(project))
    assert sym_count >= 5  # User, __init__, greet, User import, create_user
    assert dep_count >= 1  # create_user -> User at minimum

    # Step 3: Query a symbol — get signature, not whole file
    results = query_symbol(db, project_id, "User")
    user_class = next((r for r in results if r["symbol_type"] == "class"), None)
    assert user_class is not None
    assert "class User" in user_class["signature"]

    # Step 4: Get dependencies
    deps = get_symbol_dependencies(db, project_id, "create_user")
    dep_names = [d["symbol_name"] for d in deps]
    assert "User" in dep_names or "greet" in dep_names

    # Step 5: Combine with memory
    manager = MemoryManager(db, str(project))
    manager.remember(
        file_path="service.py",
        symbol_name="create_user",
        notes="creates User and calls greet — entry point for user creation flow",
    )

    memories = manager.recall("create_user")
    assert len(memories) == 1
    assert memories[0]["symbol_name"] == "create_user"
