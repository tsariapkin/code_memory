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


def test_extract_dependencies_finds_inheritance(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text("class Base:\n    pass\n\n\nclass Child(Base):\n    pass\n")
    deps = extract_dependencies(str(code_file))
    inherits = [d for d in deps if d["dep_type"] == "inherits"]
    assert len(inherits) == 1
    assert inherits[0]["source"] == "Child"
    assert inherits[0]["target"] == "Base"


def test_extract_dependencies_finds_multiple_inheritance(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text("class A:\n    pass\n\nclass B:\n    pass\n\nclass C(A, B):\n    pass\n")
    deps = extract_dependencies(str(code_file))
    inherits = [d for d in deps if d["dep_type"] == "inherits"]
    targets = [d["target"] for d in inherits]
    assert "A" in targets
    assert "B" in targets


def test_extract_dependencies_finds_import_edges(tmp_path):
    code_file = tmp_path / "example.py"
    code_file.write_text(
        "from pathlib import Path\nimport os\n\ndef read_file(name):\n    return Path(name).read_text()\n"
    )
    deps = extract_dependencies(str(code_file))
    import_deps = [d for d in deps if d["dep_type"] == "imports"]
    # read_file imports Path (used in body)
    assert any(d["source"] == "read_file" and d["target"] == "Path" for d in import_deps)


def test_get_symbol_dependencies(db, python_project):
    project_id = db.get_or_create_project(str(python_project))
    index_project_files(db, project_id, str(python_project))

    deps = get_symbol_dependencies(db, project_id, "login")
    dep_names = [d["symbol_name"] for d in deps]
    assert "verify" in dep_names


def test_method_call_resolves_to_class_method(db, tmp_path):
    """self.method() and obj.method() should resolve to ClassName.method."""
    (tmp_path / "service.py").write_text(
        "class UserService:\n"
        "    def validate(self):\n"
        "        return True\n\n"
        "    def create(self):\n"
        "        return self.validate()\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    sym_count, dep_count = index_project_files(db, project_id, str(tmp_path))

    # The call self.validate() should create a dependency to UserService.validate
    deps = db.execute(
        """SELECT s.symbol_name as source, t.symbol_name as target, d.dep_type
           FROM dependencies d
           JOIN symbols s ON d.source_id = s.id
           JOIN symbols t ON d.target_id = t.id
           WHERE s.project_id = ?""",
        (project_id,),
    ).fetchall()
    dep_pairs = [(dict(d)["source"], dict(d)["target"]) for d in deps]
    assert ("UserService.create", "UserService.validate") in dep_pairs


def test_cross_file_method_call_resolution(db, tmp_path):
    """Function calling obj.method() across files should resolve correctly."""
    (tmp_path / "models.py").write_text("class User:\n" "    def save(self):\n" "        pass\n")
    (tmp_path / "views.py").write_text(
        "def create_user(data):\n" "    u = User()\n" "    u.save()\n" "    return u\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    index_project_files(db, project_id, str(tmp_path))

    deps = get_symbol_dependencies(db, project_id, "create_user")
    dep_names = [d["symbol_name"] for d in deps]
    assert "User.save" in dep_names


def test_same_name_functions_across_files_no_collision(db, tmp_path):
    """Two files with same-named helper() should both get dependencies stored."""
    (tmp_path / "a.py").write_text(
        "def helper():\n    return 1\n\n" "def use_a():\n    return helper()\n"
    )
    (tmp_path / "b.py").write_text(
        "def helper():\n    return 2\n\n" "def use_b():\n    return helper()\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    sym_count, dep_count = index_project_files(db, project_id, str(tmp_path))

    # Both use_a -> helper and use_b -> helper should exist
    deps_a = get_symbol_dependencies(db, project_id, "use_a")
    deps_b = get_symbol_dependencies(db, project_id, "use_b")
    assert any(d["symbol_name"] == "helper" for d in deps_a)
    assert any(d["symbol_name"] == "helper" for d in deps_b)


def test_get_callers_finds_method_callers(db, tmp_path):
    """get_callers should find callers of methods called via attribute access."""
    from src.code_memory.graph_engine import CodeGraph

    (tmp_path / "service.py").write_text(
        "class DB:\n"
        "    def query(self):\n"
        "        return []\n\n"
        "def fetch_data():\n"
        "    db = DB()\n"
        "    return db.query()\n"
    )
    project_id = db.get_or_create_project(str(tmp_path))
    index_project_files(db, project_id, str(tmp_path))

    graph = CodeGraph()
    graph.build_from_db(db, project_id)

    callers = graph.get_callers("DB.query")
    caller_names = [c["symbol_name"] for c in callers]
    assert "fetch_data" in caller_names
