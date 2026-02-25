# Multi-Language Support

**Date:** 2026-02-25
**Status:** Approved

## Problem

The symbol indexer only supports Python. Users working on polyglot codebases (Python + JS/TS + Go) can't index or query symbols in non-Python files.

## Design

Add JavaScript/TypeScript and Go support to the existing `symbol_indexer.py` using a config-driven approach. Each language is defined by a config dict that maps tree-sitter node types to symbol extraction rules. Language-specific edge cases are handled by small helper functions.

### Priority Order

1. JavaScript/TypeScript
2. Go

### Language Configs

Module-level `LANGUAGE_CONFIGS` dict in `symbol_indexer.py`, keyed by language name:

```python
LANGUAGE_CONFIGS = {
    "python": {
        "extensions": [".py"],
        "grammar_module": "tree_sitter_python",
        "symbol_nodes": {
            "function_definition": "function",
            "class_definition": "class",
        },
        "method_parent": "class_definition",
        "import_nodes": ["import_statement", "import_from_statement"],
        "superclass_field": "superclasses",
    },
    "javascript": {
        "extensions": [".js", ".jsx"],
        "grammar_module": "tree_sitter_javascript",
        "symbol_nodes": {
            "function_declaration": "function",
            "class_declaration": "class",
            "arrow_function": "function",
            "interface_declaration": "interface",
            "type_alias_declaration": "type_alias",
            "export_statement": None,
        },
        "method_parent": "class_declaration",
        "import_nodes": ["import_statement"],
        "superclass_field": "extends_clause",
    },
    "typescript": {
        "extensions": [".ts", ".tsx"],
        "grammar_module": "tree_sitter_typescript",
        # Same extraction rules as javascript, different grammar
        ...
    },
    "go": {
        "extensions": [".go"],
        "grammar_module": "tree_sitter_go",
        "symbol_nodes": {
            "function_declaration": "function",
            "method_declaration": "method",
            "type_declaration": None,
        },
        "struct_node": "struct_type",
        "interface_node": "interface_type",
        "import_nodes": ["import_declaration"],
    },
}
```

Extension-to-language mapping is derived from configs at module load time.

### Grammar Lazy-Loading

Grammars are imported via `importlib.import_module` only when a file of that language is first encountered. Cached in module-level dicts. If a grammar package isn't installed, files of that language are skipped (not a crash).

```python
_grammars: dict[str, Language] = {}
_parsers: dict[str, Parser] = {}

def _get_parser(language: str) -> Parser:
    if language not in _parsers:
        config = LANGUAGE_CONFIGS[language]
        module = importlib.import_module(config["grammar_module"])
        _grammars[language] = Language(module.language())
        _parsers[language] = Parser(_grammars[language])
    return _parsers[language]
```

### Symbol Types

| Symbol Type | Languages | Example |
|-------------|-----------|---------|
| `function` | All | `def foo()`, `function foo()`, `func foo()` |
| `class` | Python, JS/TS | `class Foo`, `class Foo extends Bar` |
| `method` | All | `def bar(self)`, `bar() {}`, `func (r *T) bar()` |
| `import` | All | `import os`, `import x from 'y'`, `import "fmt"` |
| `interface` | JS/TS, Go | `interface Foo {}`, `type Foo interface{}` |
| `struct` | Go | `type Foo struct{}` |
| `type_alias` | JS/TS | `type Foo = Bar & Baz` |

### Dependency Edges

| Edge Type | Python | JS/TS | Go |
|-----------|--------|-------|-----|
| `calls` | function calls | function calls | function calls |
| `imports` | `import`/`from...import` | `import...from` | `import "pkg"` |
| `inherits` | class superclasses | `extends` clause | embedded struct types |
| `implements` | -- | `implements` clause | -- (implicit in Go) |

### Refactored Functions

- `parse_file_symbols(file_path, language=None)` -- detects language from extension if not given, uses config to drive extraction
- `extract_dependencies(file_path, language=None)` -- same config-driven approach
- `_collect_python_files` becomes `_collect_source_files` -- collects files of all supported extensions, returns `(full_path, rel_path, language)` tuples
- Language-specific helpers: `_extract_go_methods`, `_extract_js_exports`, `_extract_ts_types`

### Files Changed

| File | Change |
|------|--------|
| `symbol_indexer.py` | Add configs, lazy loading, refactor to be language-aware |
| `mcp_tools.py` | Update index_project description |
| `pyproject.toml` | Add tree-sitter-javascript, tree-sitter-typescript, tree-sitter-go |
| `README.md` | Update for multi-language support |
| Tests | Add per-language symbol extraction and dependency tests |

### What Stays Unchanged

- `db.py` -- schema already has `language` column
- `graph_engine.py` -- language-agnostic
- `memory_manager.py`, `git_utils.py` -- no changes
- All MCP tool signatures -- unchanged
- Existing SQLite databases -- backwards compatible

## Constraints

- All 9 MCP tool signatures unchanged
- Existing Python-only databases continue to work
- Missing grammar packages skip that language, don't crash
- New languages indexed alongside Python on next `index_project()` call
