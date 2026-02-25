from src.code_memory.symbol_indexer import LANGUAGE_CONFIGS, _get_parser, get_language_for_ext


def test_language_configs_has_all_languages():
    assert "python" in LANGUAGE_CONFIGS
    assert "javascript" in LANGUAGE_CONFIGS
    assert "typescript" in LANGUAGE_CONFIGS
    assert "go" in LANGUAGE_CONFIGS


def test_python_extensions():
    assert LANGUAGE_CONFIGS["python"]["extensions"] == [".py"]


def test_js_extensions():
    assert ".js" in LANGUAGE_CONFIGS["javascript"]["extensions"]
    assert ".jsx" in LANGUAGE_CONFIGS["javascript"]["extensions"]


def test_ts_extensions():
    assert ".ts" in LANGUAGE_CONFIGS["typescript"]["extensions"]
    assert ".tsx" in LANGUAGE_CONFIGS["typescript"]["extensions"]


def test_go_extensions():
    assert LANGUAGE_CONFIGS["go"]["extensions"] == [".go"]


def test_get_language_for_ext():
    assert get_language_for_ext(".py") == "python"
    assert get_language_for_ext(".js") == "javascript"
    assert get_language_for_ext(".jsx") == "javascript"
    assert get_language_for_ext(".ts") == "typescript"
    assert get_language_for_ext(".tsx") == "typescript"
    assert get_language_for_ext(".go") == "go"
    assert get_language_for_ext(".rb") is None


def test_get_parser_python():
    parser = _get_parser("python")
    assert parser is not None


def test_get_parser_javascript():
    parser = _get_parser("javascript")
    assert parser is not None


def test_get_parser_typescript():
    parser = _get_parser("typescript")
    assert parser is not None


def test_get_parser_go():
    parser = _get_parser("go")
    assert parser is not None


def test_get_parser_caches():
    p1 = _get_parser("python")
    p2 = _get_parser("python")
    assert p1 is p2
