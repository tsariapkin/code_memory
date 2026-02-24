import pytest

from src.code_memory.db import Database
from src.code_memory.symbol_indexer import (
    extract_dependencies,
    get_symbol_dependencies,
    index_project_files,
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
    (tmp_path / "auth.py").write_text(
        "from utils import verify\n\n\ndef login(user, password):\n    return verify(user, password)\n"
    )
    (tmp_path / "utils.py").write_text('def verify(user, password):\n    return user == "admin"\n')
    return tmp_path


def test_extract_dependencies_finds_calls(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "def foo():\n    return bar() + baz()\n\ndef bar():\n    return 1\n\ndef baz():\n    return 2\n"
    )
    deps = extract_dependencies(str(code_file))
    # foo calls bar and baz
    foo_deps = [d for d in deps if d["source"] == "foo"]
    target_names = [d["target"] for d in foo_deps]
    assert "bar" in target_names
    assert "baz" in target_names


def test_extract_dependencies_finds_imports(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "from pathlib import Path\n\ndef read_file(name):\n    return Path(name).read_text()\n"
    )
    deps = extract_dependencies(str(code_file))
    read_deps = [d for d in deps if d["source"] == "read_file"]
    target_names = [d["target"] for d in read_deps]
    assert "Path" in target_names


def test_get_symbol_dependencies(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    index_project_files(db, project_id, str(python_project))

    deps = get_symbol_dependencies(db, project_id, "login")
    dep_names = [d["symbol_name"] for d in deps]
    assert "verify" in dep_names
