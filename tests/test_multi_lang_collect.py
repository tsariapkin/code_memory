from src.code_memory.symbol_indexer import _collect_source_files


def test_collects_python_files(tmp_path):
    (tmp_path / "main.py").write_text("x = 1")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 1
    assert result[0][1] == "main.py"
    assert result[0][2] == "python"


def test_collects_js_files(tmp_path):
    (tmp_path / "app.js").write_text("const x = 1;")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 1
    assert result[0][2] == "javascript"


def test_collects_ts_files(tmp_path):
    (tmp_path / "app.ts").write_text("const x: number = 1;")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 1
    assert result[0][2] == "typescript"


def test_collects_go_files(tmp_path):
    (tmp_path / "main.go").write_text("package main")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 1
    assert result[0][2] == "go"


def test_collects_mixed_languages(tmp_path):
    (tmp_path / "main.py").write_text("x = 1")
    (tmp_path / "app.js").write_text("const x = 1;")
    (tmp_path / "main.go").write_text("package main")
    (tmp_path / "readme.txt").write_text("ignore me")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 3
    langs = {r[2] for r in result}
    assert langs == {"python", "javascript", "go"}


def test_skips_node_modules(tmp_path):
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "dep.js").write_text("module.exports = {};")
    (tmp_path / "app.js").write_text("const x = 1;")
    result = _collect_source_files(str(tmp_path))
    assert len(result) == 1


def test_only_files_filter(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.js").write_text("const y = 2;")
    (tmp_path / "c.go").write_text("package main")
    result = _collect_source_files(str(tmp_path), only_files=["a.py", "b.js"])
    assert len(result) == 2
    langs = {r[2] for r in result}
    assert langs == {"python", "javascript"}
