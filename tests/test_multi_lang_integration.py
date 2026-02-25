from src.code_memory.db import Database
from src.code_memory.symbol_indexer import index_project_files


def _setup_db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.initialize()
    project_id = db.get_or_create_project(str(tmp_path / "project"))
    return db, project_id


def test_index_mixed_language_project(tmp_path):
    """Index a project with Python, JS, and Go files."""
    project = tmp_path / "project"
    project.mkdir()

    (project / "main.py").write_text("""\
def hello():
    return "hello"

class Service:
    def run(self):
        hello()
""")

    (project / "app.js").write_text("""\
function greet(name) {
    return `Hello ${name}`;
}

class Widget {
    render() {
        greet("world");
    }
}
""")

    (project / "main.go").write_text("""\
package main

import "fmt"

func greet(name string) string {
    return fmt.Sprintf("Hello %s", name)
}

func main() {
    greet("world")
}
""")

    db, project_id = _setup_db(tmp_path)
    sym_count, dep_count = index_project_files(db, project_id, str(project))

    rows = db.execute(
        "SELECT DISTINCT language FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    languages = {row[0] for row in rows}
    assert "python" in languages
    assert "javascript" in languages
    assert "go" in languages

    for lang in ("python", "javascript", "go"):
        count = db.execute(
            "SELECT COUNT(*) FROM symbols WHERE project_id = ? AND language = ?",
            (project_id, lang),
        ).fetchone()[0]
        assert count > 0, f"No symbols found for {lang}"

    assert sym_count > 0
    assert dep_count > 0


def test_incremental_index_mixed_languages(tmp_path):
    """Incremental indexing works across languages."""
    project = tmp_path / "project"
    project.mkdir()

    (project / "main.py").write_text("def foo(): pass")
    (project / "app.js").write_text("function bar() {}")

    db, project_id = _setup_db(tmp_path)

    sym1, dep1 = index_project_files(db, project_id, str(project))
    assert sym1 > 0

    sym2, dep2 = index_project_files(db, project_id, str(project), changed_files=["app.js"])
    assert sym2 > 0

    py_count = db.execute(
        "SELECT COUNT(*) FROM symbols WHERE project_id = ? AND language = 'python'",
        (project_id,),
    ).fetchone()[0]
    assert py_count > 0


def test_unsupported_files_skipped(tmp_path):
    """Files with unsupported extensions are silently skipped."""
    project = tmp_path / "project"
    project.mkdir()

    (project / "main.py").write_text("def foo(): pass")
    (project / "data.csv").write_text("a,b,c")
    (project / "notes.md").write_text("# Notes")

    db, project_id = _setup_db(tmp_path)
    sym_count, _ = index_project_files(db, project_id, str(project))

    rows = db.execute(
        "SELECT DISTINCT language FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    languages = {row[0] for row in rows}
    assert languages == {"python"}
