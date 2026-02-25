import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.embedding_engine import EmbeddingEngine
from src.code_memory.memory_manager import MemoryManager


@pytest.fixture
def git_repo(tmp_path):
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
    (tmp_path / "app.py").write_text("def login(): pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.fixture
def manager(git_repo, tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    engine = EmbeddingEngine()
    mgr = MemoryManager(db, str(git_repo), embedding_engine=engine)
    yield mgr
    db.close()


def test_remember_and_recall(manager):
    manager.remember(file_path="app.py", symbol_name="login", notes="handles JWT auth")
    results = manager.recall(query="login")
    assert len(results) == 1
    assert results[0]["notes"] == "handles JWT auth"
    assert results[0]["is_stale"] is False


def test_recall_by_file(manager):
    manager.remember(file_path="app.py", notes="main application file")
    results = manager.recall(query="app.py")
    assert len(results) == 1


def test_forget(manager):
    manager.remember(file_path="app.py", notes="to be forgotten")
    results = manager.recall(query="app.py")
    memory_id = results[0]["id"]

    manager.forget(memory_id)
    results = manager.recall(query="app.py")
    assert len(results) == 0


def test_staleness_detection(manager, git_repo):
    manager.remember(file_path="app.py", symbol_name="login", notes="original impl")

    # Modify and commit
    (git_repo / "app.py").write_text("def login(): return True\n")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "change login"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    results = manager.recall(query="login")
    assert len(results) == 1
    assert results[0]["is_stale"] is True


def test_get_project_summary(manager):
    manager.remember(file_path="app.py", notes="note 1")
    manager.remember(file_path="utils.py", notes="note 2")
    summary = manager.get_project_summary()
    assert summary["total_memories"] == 2
    assert summary["stale_memories"] == 0
    assert len(summary["recent_memories"]) == 2


def test_remember_stores_embedding(manager):
    manager.remember(file_path="app.py", symbol_name="login", notes="handles JWT auth")
    row = manager.db.execute(
        "SELECT * FROM embeddings WHERE project_id = ? AND source_type = 'memory'",
        (manager.project_id,),
    ).fetchone()
    assert row is not None
    assert "JWT" in dict(row)["text"]


def test_forget_deletes_embedding(manager):
    mid = manager.remember(file_path="app.py", notes="to be forgotten")
    manager.forget(mid)
    row = manager.db.execute(
        "SELECT * FROM embeddings WHERE project_id = ? AND source_type = 'memory' AND source_id = ?",
        (manager.project_id, mid),
    ).fetchone()
    assert row is None


def test_semantic_search_finds_by_meaning(manager):
    manager.remember(file_path="models.py", symbol_name="Product", notes="e-commerce product model")
    manager.remember(file_path="auth.py", symbol_name="login", notes="handles user authentication")
    results = manager.semantic_search("shopping item class")
    assert len(results) > 0
    assert results[0]["source_type"] == "memory"
    assert "product" in results[0]["notes"].lower()


def test_semantic_search_word_order_invariant(manager):
    manager.remember(notes="Product relates to Origin via foreign key")
    r1 = manager.semantic_search("Product Origin")
    r2 = manager.semantic_search("Origin Product")
    assert len(r1) > 0
    assert len(r2) > 0
    assert r1[0]["source_id"] == r2[0]["source_id"]


def test_semantic_search_returns_empty_without_engine(git_repo, tmp_path):
    db = Database(str(tmp_path / "test2.db"))
    db.initialize()
    mgr = MemoryManager(db, str(git_repo), embedding_engine=None)
    mgr.remember(notes="some note")
    results = mgr.semantic_search("note")
    assert results == []
    db.close()
