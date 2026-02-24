from src.code_memory.symbol_indexer import parse_file_symbols

SAMPLE_CODE = '''\
import os
from pathlib import Path


def greet(name: str) -> str:
    """Greet someone."""
    return f"Hello {name}"


class UserService:
    """Manages users."""

    def __init__(self, db):
        self.db = db

    def get_user(self, user_id: int):
        return self.db.find(user_id)

    def delete_user(self, user_id: int):
        self.db.delete(user_id)
'''


def test_parse_extracts_functions(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    func_names = [s["symbol_name"] for s in symbols if s["symbol_type"] == "function"]
    assert "greet" in func_names


def test_parse_extracts_classes(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    class_names = [s["symbol_name"] for s in symbols if s["symbol_type"] == "class"]
    assert "UserService" in class_names


def test_parse_extracts_methods(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    method_names = [s["symbol_name"] for s in symbols if s["symbol_type"] == "method"]
    assert "UserService.__init__" in method_names
    assert "UserService.get_user" in method_names
    assert "UserService.delete_user" in method_names


def test_parse_extracts_imports(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    import_names = [s["symbol_name"] for s in symbols if s["symbol_type"] == "import"]
    assert "os" in import_names
    assert "Path" in import_names


def test_parse_includes_line_ranges(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert greet["line_start"] is not None
    assert greet["line_end"] is not None
    assert greet["line_end"] > greet["line_start"]


def test_parse_includes_signature(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert "def greet" in greet["signature"]
    assert "name: str" in greet["signature"]


def test_parse_includes_content_hash(tmp_path):
    f = tmp_path / "sample.py"
    f.write_text(SAMPLE_CODE)
    symbols = parse_file_symbols(str(f))

    greet = next(s for s in symbols if s["symbol_name"] == "greet")
    assert greet["content_hash"] is not None
    assert len(greet["content_hash"]) > 0
