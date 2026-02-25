import subprocess

import pytest

from src.code_memory.db import Database
from src.code_memory.embedding_engine import EmbeddingEngine
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import index_project_files


@pytest.fixture
def project_with_symbols(tmp_path):
    """Create a git repo with two related classes and index them."""
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t.com"], cwd=project, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "T"], cwd=project, check=True, capture_output=True
    )

    (project / "models.py").write_text(
        "from origin import Origin\n\n"
        "class Product:\n"
        "    def __init__(self, name: str, origin: Origin):\n"
        "        self.name = name\n"
        "        self.origin = origin\n"
    )
    (project / "origin.py").write_text(
        "class Origin:\n"
        "    def __init__(self, country: str):\n"
        "        self.country = country\n"
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)

    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    engine = EmbeddingEngine()
    manager = MemoryManager(db, str(project), embedding_engine=engine)
    project_id = manager.project_id

    # Index symbols
    index_project_files(db, project_id, str(project))

    # Embed all symbols
    rows = db.execute(
        "SELECT id, symbol_name, symbol_type, signature, file_path FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    for row in rows:
        row = dict(row)
        text = (
            f"{row['symbol_name']} {row['symbol_type']} {row['signature'] or ''} {row['file_path']}"
        )
        vec = engine.embed(text)
        blob = engine.vector_to_blob(vec)
        db.execute(
            "INSERT OR REPLACE INTO embeddings (project_id, source_type, source_id, text, vector) "
            "VALUES (?, 'symbol', ?, ?, ?)",
            (project_id, row["id"], text, blob),
        )
    db.conn.commit()

    yield manager, db, project_id
    db.close()


def test_semantic_search_finds_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    results = manager.semantic_search("Product")
    symbol_names = [r.get("symbol_name", "") for r in results]
    assert "Product" in symbol_names


def test_semantic_search_word_order_for_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    r1 = manager.semantic_search("Product Origin")
    r2 = manager.semantic_search("Origin Product")
    assert len(r1) > 0
    assert len(r2) > 0
    names1 = {r.get("symbol_name") for r in r1[:3]}
    names2 = {r.get("symbol_name") for r in r2[:3]}
    assert names1 & names2  # Should overlap


def test_semantic_search_mixed_memories_and_symbols(project_with_symbols):
    manager, db, project_id = project_with_symbols
    manager.remember(notes="Product uses Origin via foreign key", file_path="models.py")
    results = manager.semantic_search("how Product connects to Origin")
    source_types = {r["source_type"] for r in results}
    assert "memory" in source_types
    assert "symbol" in source_types


def test_search_finds_both_related_symbols(project_with_symbols):
    """Searching 'Product Origin' should return both symbols via semantic similarity."""
    manager, db, project_id = project_with_symbols

    results = manager.semantic_search("Product Origin")
    names = [r.get("symbol_name") for r in results]
    assert "Product" in names
    assert "Origin" in names
