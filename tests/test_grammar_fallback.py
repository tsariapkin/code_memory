from unittest.mock import patch

from src.code_memory.symbol_indexer import _get_parser, _grammars, _parsers, parse_file_symbols


def test_missing_grammar_returns_empty(tmp_path):
    """If a grammar package isn't installed, parsing returns empty list."""
    f = tmp_path / "app.js"
    f.write_text("function foo() {}")

    _parsers.pop("javascript", None)

    with patch("src.code_memory.symbol_indexer.importlib.import_module", side_effect=ImportError):
        symbols = parse_file_symbols(str(f), language="javascript")
    assert symbols == []
    _parsers.pop("javascript", None)
    _grammars.pop("javascript", None)


def test_missing_grammar_does_not_crash_get_parser(tmp_path):
    """_get_parser returns None when grammar package is missing."""
    _parsers.pop("javascript", None)

    with patch("src.code_memory.symbol_indexer.importlib.import_module", side_effect=ImportError):
        parser = _get_parser("javascript")
    assert parser is None
    _parsers.pop("javascript", None)
    _grammars.pop("javascript", None)
