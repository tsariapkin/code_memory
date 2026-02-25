from __future__ import annotations

import hashlib
import importlib
import os

from tree_sitter import Language, Parser

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
            "export_statement": None,
        },
        "method_parent": "class_declaration",
        "import_nodes": ["import_statement"],
        "superclass_field": "extends_clause",
    },
    "typescript": {
        "extensions": [".ts", ".tsx"],
        "grammar_module": "tree_sitter_typescript",
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

# Build extension-to-language lookup at module load time
_EXT_TO_LANG: dict[str, str] = {}
for _lang, _cfg in LANGUAGE_CONFIGS.items():
    for _ext in _cfg["extensions"]:
        _EXT_TO_LANG[_ext] = _lang


def get_language_for_ext(ext: str) -> str | None:
    """Return language name for a file extension, or None if unsupported."""
    return _EXT_TO_LANG.get(ext)


# Lazy-loaded grammar caches
_grammars: dict[str, Language] = {}
_parsers: dict[str, Parser] = {}


# Directories to skip during project indexing
SKIP_DIRS = frozenset(
    {
        # Python
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".env",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".pytype",
        "*.egg-info",
        "dist",
        "build",
        "site-packages",
        # JavaScript / Node
        "node_modules",
        "bower_components",
        ".next",
        ".nuxt",
        # General
        ".git",
        ".hg",
        ".svn",
        ".cache",
        "vendor",
        ".terraform",
        ".serverless",
    }
)


def _get_parser(language: str = "python") -> Parser:
    """Get or create a tree-sitter parser for the given language."""
    if language not in _parsers:
        config = LANGUAGE_CONFIGS[language]
        module = importlib.import_module(config["grammar_module"])
        if language == "typescript":
            _grammars[language] = Language(module.language_typescript())
        else:
            _grammars[language] = Language(module.language())
        _parsers[language] = Parser(_grammars[language])
    return _parsers[language]


def _content_hash(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()[:16]


def _extract_signature(node) -> str:
    """Extract the first line of a function/class definition as its signature."""
    text = node.text.decode("utf-8")
    first_line = text.split("\n")[0]
    return first_line.rstrip(":")


def _parse_python_symbols(root, source: bytes) -> list[dict]:
    """Extract symbols from a Python AST root node."""
    symbols = []

    for child in root.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            symbols.append(
                {
                    "symbol_name": name_node.text.decode("utf-8"),
                    "symbol_type": "function",
                    "line_start": child.start_point[0] + 1,
                    "line_end": child.end_point[0] + 1,
                    "signature": _extract_signature(child),
                    "content_hash": _content_hash(child.text),
                    "base_classes": [],
                }
            )

        elif child.type == "class_definition":
            class_name_node = child.child_by_field_name("name")
            class_name = class_name_node.text.decode("utf-8")

            # Extract base classes from superclasses node
            base_classes = []
            superclasses = child.child_by_field_name("superclasses")
            if superclasses:
                for arg in superclasses.named_children:
                    if arg.type == "identifier":
                        base_classes.append(arg.text.decode("utf-8"))
                    elif arg.type == "attribute":
                        base_classes.append(arg.text.decode("utf-8"))

            symbols.append(
                {
                    "symbol_name": class_name,
                    "symbol_type": "class",
                    "line_start": child.start_point[0] + 1,
                    "line_end": child.end_point[0] + 1,
                    "signature": _extract_signature(child),
                    "content_hash": _content_hash(child.text),
                    "base_classes": base_classes,
                }
            )

            # Extract methods
            body = child.child_by_field_name("body")
            if body:
                for body_child in body.children:
                    if body_child.type == "function_definition":
                        method_name_node = body_child.child_by_field_name("name")
                        method_name = method_name_node.text.decode("utf-8")
                        symbols.append(
                            {
                                "symbol_name": f"{class_name}.{method_name}",
                                "symbol_type": "method",
                                "line_start": body_child.start_point[0] + 1,
                                "line_end": body_child.end_point[0] + 1,
                                "signature": _extract_signature(body_child),
                                "content_hash": _content_hash(body_child.text),
                                "base_classes": [],
                            }
                        )

        elif child.type == "import_statement":
            for named_child in child.named_children:
                if named_child.type == "dotted_name":
                    symbols.append(
                        {
                            "symbol_name": named_child.text.decode("utf-8"),
                            "symbol_type": "import",
                            "line_start": child.start_point[0] + 1,
                            "line_end": child.end_point[0] + 1,
                            "signature": child.text.decode("utf-8").strip(),
                            "content_hash": _content_hash(child.text),
                            "base_classes": [],
                        }
                    )
                elif named_child.type == "aliased_import":
                    name = named_child.child_by_field_name("name")
                    if name:
                        symbols.append(
                            {
                                "symbol_name": name.text.decode("utf-8"),
                                "symbol_type": "import",
                                "line_start": child.start_point[0] + 1,
                                "line_end": child.end_point[0] + 1,
                                "signature": child.text.decode("utf-8").strip(),
                                "content_hash": _content_hash(child.text),
                                "base_classes": [],
                            }
                        )

        elif child.type == "import_from_statement":
            # The first dotted_name is the module name; subsequent ones are imported names
            module_node = child.child_by_field_name("module_name")
            for named_child in child.named_children:
                if named_child.type == "dotted_name":
                    if module_node and named_child.id == module_node.id:
                        continue  # module name, skip
                    symbols.append(
                        {
                            "symbol_name": named_child.text.decode("utf-8"),
                            "symbol_type": "import",
                            "line_start": child.start_point[0] + 1,
                            "line_end": child.end_point[0] + 1,
                            "signature": child.text.decode("utf-8").strip(),
                            "content_hash": _content_hash(child.text),
                            "base_classes": [],
                        }
                    )
                elif named_child.type == "aliased_import":
                    name = named_child.child_by_field_name("name")
                    if name:
                        symbols.append(
                            {
                                "symbol_name": name.text.decode("utf-8"),
                                "symbol_type": "import",
                                "line_start": child.start_point[0] + 1,
                                "line_end": child.end_point[0] + 1,
                                "signature": child.text.decode("utf-8").strip(),
                                "content_hash": _content_hash(child.text),
                                "base_classes": [],
                            }
                        )

    return symbols


def _parse_js_symbols(root, source: bytes) -> list[dict]:
    """Extract symbols from a JavaScript AST root node."""
    symbols = []

    def _process_js_node(node):
        """Process a single top-level JS node (may be unwrapped from export_statement)."""
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(
                    {
                        "symbol_name": name_node.text.decode("utf-8"),
                        "symbol_type": "function",
                        "line_start": node.start_point[0] + 1,
                        "line_end": node.end_point[0] + 1,
                        "signature": _extract_signature(node),
                        "content_hash": _content_hash(node.text),
                        "base_classes": [],
                    }
                )

        elif node.type in ("lexical_declaration", "variable_declaration"):
            # Look for arrow functions: const fetchData = async (url) => { ... };
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    value_node = declarator.child_by_field_name("value")
                    if name_node and value_node and value_node.type == "arrow_function":
                        symbols.append(
                            {
                                "symbol_name": name_node.text.decode("utf-8"),
                                "symbol_type": "function",
                                "line_start": node.start_point[0] + 1,
                                "line_end": node.end_point[0] + 1,
                                "signature": _extract_signature(node),
                                "content_hash": _content_hash(node.text),
                                "base_classes": [],
                            }
                        )

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            class_name = name_node.text.decode("utf-8")

            # Extract base classes from class_heritage
            base_classes = []
            for child in node.children:
                if child.type == "class_heritage":
                    for heritage_child in child.named_children:
                        if heritage_child.type == "identifier":
                            base_classes.append(heritage_child.text.decode("utf-8"))
                        elif heritage_child.type == "member_expression":
                            base_classes.append(heritage_child.text.decode("utf-8"))

            symbols.append(
                {
                    "symbol_name": class_name,
                    "symbol_type": "class",
                    "line_start": node.start_point[0] + 1,
                    "line_end": node.end_point[0] + 1,
                    "signature": _extract_signature(node),
                    "content_hash": _content_hash(node.text),
                    "base_classes": base_classes,
                }
            )

            # Extract methods from class_body
            body_node = node.child_by_field_name("body")
            if body_node:
                for body_child in body_node.named_children:
                    if body_child.type == "method_definition":
                        method_name_node = body_child.child_by_field_name("name")
                        if method_name_node:
                            method_name = method_name_node.text.decode("utf-8")
                            symbols.append(
                                {
                                    "symbol_name": f"{class_name}.{method_name}",
                                    "symbol_type": "method",
                                    "line_start": body_child.start_point[0] + 1,
                                    "line_end": body_child.end_point[0] + 1,
                                    "signature": _extract_signature(body_child),
                                    "content_hash": _content_hash(body_child.text),
                                    "base_classes": [],
                                }
                            )

        elif node.type == "import_statement":
            # JS import: import { useState } from 'react'; or import axios from 'axios';
            for child in node.children:
                if child.type == "import_clause":
                    _extract_js_import_names(child, node, symbols)

    for child in root.children:
        if child.type == "export_statement":
            # Unwrap exported declarations
            for export_child in child.named_children:
                if export_child.type in (
                    "function_declaration",
                    "class_declaration",
                    "lexical_declaration",
                    "variable_declaration",
                ):
                    _process_js_node(export_child)
        else:
            _process_js_node(child)

    return symbols


def _extract_js_import_names(import_clause, import_node, symbols: list):
    """Extract import symbol names from a JS import_clause node."""
    for child in import_clause.children:
        if child.type == "identifier":
            # Default import: import axios from 'axios';
            symbols.append(
                {
                    "symbol_name": child.text.decode("utf-8"),
                    "symbol_type": "import",
                    "line_start": import_node.start_point[0] + 1,
                    "line_end": import_node.end_point[0] + 1,
                    "signature": import_node.text.decode("utf-8").strip(),
                    "content_hash": _content_hash(import_node.text),
                    "base_classes": [],
                }
            )
        elif child.type == "named_imports":
            # Named imports: import { useState, useEffect } from 'react';
            for specifier in child.named_children:
                if specifier.type == "import_specifier":
                    name_node = specifier.child_by_field_name("name")
                    if name_node:
                        symbols.append(
                            {
                                "symbol_name": name_node.text.decode("utf-8"),
                                "symbol_type": "import",
                                "line_start": import_node.start_point[0] + 1,
                                "line_end": import_node.end_point[0] + 1,
                                "signature": import_node.text.decode("utf-8").strip(),
                                "content_hash": _content_hash(import_node.text),
                                "base_classes": [],
                            }
                        )
        elif child.type == "namespace_import":
            # import * as foo from 'bar';
            for ns_child in child.children:
                if ns_child.type == "identifier":
                    symbols.append(
                        {
                            "symbol_name": ns_child.text.decode("utf-8"),
                            "symbol_type": "import",
                            "line_start": import_node.start_point[0] + 1,
                            "line_end": import_node.end_point[0] + 1,
                            "signature": import_node.text.decode("utf-8").strip(),
                            "content_hash": _content_hash(import_node.text),
                            "base_classes": [],
                        }
                    )


def _ts_fix_class_bases(root, symbols: list[dict]):
    """Fix base_classes for TypeScript classes.

    The TS tree-sitter grammar nests the superclass identifier inside
    class_heritage > extends_clause > identifier, whereas the JS grammar
    puts the identifier directly under class_heritage.  The JS extractor
    therefore misses TS base classes; this helper patches them.
    """
    # Build a map of class_name -> symbol dict for quick lookup
    class_syms = {s["symbol_name"]: s for s in symbols if s["symbol_type"] == "class"}

    def _visit(node):
        if node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                class_name = name_node.text.decode("utf-8")
                sym = class_syms.get(class_name)
                if sym and not sym["base_classes"]:
                    bases = []
                    for child in node.children:
                        if child.type == "class_heritage":
                            for heritage_child in child.children:
                                if heritage_child.type == "extends_clause":
                                    for ec_child in heritage_child.named_children:
                                        if ec_child.type in ("identifier", "member_expression"):
                                            bases.append(ec_child.text.decode("utf-8"))
                    if bases:
                        sym["base_classes"] = bases
        for child in node.children:
            _visit(child)

    _visit(root)


def _parse_ts_symbols(root, source: bytes) -> list[dict]:
    """Extract symbols from a TypeScript AST root node.

    Reuses the JS extraction logic and adds TypeScript-specific nodes:
    interface_declaration and type_alias_declaration.
    """
    symbols = _parse_js_symbols(root, source)

    # Fix class base_classes: TS grammar nests identifiers inside extends_clause
    # within class_heritage, unlike JS where they are direct children.
    _ts_fix_class_bases(root, symbols)

    # Second pass for TS-specific declarations
    for child in root.children:
        node = child
        # Unwrap export statements
        if child.type == "export_statement":
            for export_child in child.named_children:
                if export_child.type in ("interface_declaration", "type_alias_declaration"):
                    node = export_child
                    break
            else:
                continue

        if node.type == "interface_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(
                    {
                        "symbol_name": name_node.text.decode("utf-8"),
                        "symbol_type": "interface",
                        "line_start": node.start_point[0] + 1,
                        "line_end": node.end_point[0] + 1,
                        "signature": _extract_signature(node),
                        "content_hash": _content_hash(node.text),
                        "base_classes": [],
                    }
                )

        elif node.type == "type_alias_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                symbols.append(
                    {
                        "symbol_name": name_node.text.decode("utf-8"),
                        "symbol_type": "type_alias",
                        "line_start": node.start_point[0] + 1,
                        "line_end": node.end_point[0] + 1,
                        "signature": _extract_signature(node),
                        "content_hash": _content_hash(node.text),
                        "base_classes": [],
                    }
                )

    return symbols


def parse_file_symbols(file_path: str, language: str | None = None) -> list[dict]:
    """Parse a source file and extract all symbols (functions, classes, methods, imports).

    Returns a list of dicts with keys:
        symbol_name, symbol_type, line_start, line_end, signature, content_hash
    """
    if language is None:
        ext = os.path.splitext(file_path)[1]
        language = get_language_for_ext(ext)
        if language is None:
            return []

    if language not in ("python", "javascript", "typescript"):
        return []  # Go implemented in later tasks

    with open(file_path, "rb") as f:
        source = f.read()

    parser = _get_parser(language)
    tree = parser.parse(source)
    root = tree.root_node

    if language == "python":
        return _parse_python_symbols(root, source)
    elif language == "javascript":
        return _parse_js_symbols(root, source)
    elif language == "typescript":
        return _parse_ts_symbols(root, source)
    else:
        return []


def find_enclosing_symbol(file_path: str, line: int) -> str | None:
    """Given a file and a 1-indexed line number, return the name of the enclosing symbol.

    Returns the most specific enclosing symbol (method > class > function).
    Returns None if the line is not inside any symbol.
    """
    symbols = parse_file_symbols(file_path)

    best_match = None
    best_span = float("inf")

    for s in symbols:
        if s["symbol_type"] == "import":
            continue
        if s["line_start"] <= line <= s["line_end"]:
            span = s["line_end"] - s["line_start"]
            if span < best_span:
                best_span = span
                best_match = s["symbol_name"]

    return best_match


def _collect_source_files(
    project_root: str, only_files: list[str] | None = None
) -> list[tuple[str, str, str]]:
    """Collect (full_path, rel_path, language) tuples for all supported source files.

    If only_files is given, return only those relative paths (that exist and are supported).
    """
    if only_files is not None:
        result = []
        for rel in only_files:
            full = os.path.join(project_root, rel)
            ext = os.path.splitext(rel)[1]
            lang = get_language_for_ext(ext)
            if lang and os.path.isfile(full):
                result.append((full, rel, lang))
        return result

    result = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for filename in filenames:
            ext = os.path.splitext(filename)[1]
            lang = get_language_for_ext(ext)
            if not lang:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, project_root)
            result.append((full_path, rel_path, lang))
    return result


def index_project_files(
    db, project_id: int, project_root: str, changed_files: list[str] | None = None
) -> tuple[int, int]:
    """Parse Python files and store symbols + dependencies in one pass.

    If changed_files is provided, only index those files (incremental mode).
    Returns (symbol_count, dependency_count).
    """
    files = _collect_source_files(project_root, changed_files)

    if changed_files is not None:
        # Delete old symbols and deps for changed files
        for _, rel_path, _lang in files:
            db.execute(
                """DELETE FROM dependencies WHERE source_id IN
                   (SELECT id FROM symbols
                    WHERE project_id = ? AND file_path = ?)""",
                (project_id, rel_path),
            )
            db.execute(
                "DELETE FROM symbols WHERE project_id = ? AND file_path = ?",
                (project_id, rel_path),
            )
        # Also clean up deleted files (in changed_files but not on disk)
        for rel in changed_files:
            if get_language_for_ext(os.path.splitext(rel)[1]):
                full = os.path.join(project_root, rel)
                if not os.path.isfile(full):
                    db.execute(
                        """DELETE FROM dependencies WHERE source_id IN
                           (SELECT id FROM symbols
                            WHERE project_id = ? AND file_path = ?)""",
                        (project_id, rel),
                    )
                    db.execute(
                        "DELETE FROM symbols WHERE project_id = ? AND file_path = ?",
                        (project_id, rel),
                    )

    # Phase 1: Parse files and insert symbols
    sym_count = 0
    all_deps = []

    for full_path, rel_path, lang in files:
        try:
            symbols = parse_file_symbols(full_path, language=lang)
        except Exception:
            continue

        for sym in symbols:
            db.execute(
                """INSERT OR REPLACE INTO symbols
                   (project_id, file_path, symbol_name, symbol_type, language,
                    line_start, line_end, signature, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    rel_path,
                    sym["symbol_name"],
                    sym["symbol_type"],
                    lang,
                    sym["line_start"],
                    sym["line_end"],
                    sym["signature"],
                    sym["content_hash"],
                ),
            )
            sym_count += 1

        try:
            deps = extract_dependencies(full_path, language=lang)
            all_deps.extend(deps)
        except Exception:
            continue

    db.conn.commit()

    # Phase 2: Batch-insert dependencies using preloaded symbol map
    if changed_files is None:
        # Full reindex: clear all deps first
        db.execute(
            """DELETE FROM dependencies WHERE source_id IN
               (SELECT id FROM symbols WHERE project_id = ?)""",
            (project_id,),
        )

    rows = db.execute(
        "SELECT id, symbol_name FROM symbols WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    symbol_map = {row["symbol_name"]: row["id"] for row in rows}

    dep_rows = []
    for dep in all_deps:
        source_id = symbol_map.get(dep["source"])
        target_id = symbol_map.get(dep["target"])
        if source_id and target_id:
            dep_rows.append((source_id, target_id, dep["dep_type"]))

    if dep_rows:
        db.conn.executemany(
            "INSERT OR IGNORE INTO dependencies (source_id, target_id, dep_type) VALUES (?, ?, ?)",
            dep_rows,
        )
    db.conn.commit()

    return sym_count, len(dep_rows)


def query_symbol(db, project_id: int, name: str) -> list[dict]:
    """Query symbols by name (partial match). Returns list of symbol dicts."""
    rows = db.execute(
        """SELECT file_path, symbol_name, symbol_type, line_start, line_end,
                  signature, content_hash
           FROM symbols
           WHERE project_id = ? AND symbol_name LIKE ?
           ORDER BY symbol_name""",
        (project_id, f"%{name}%"),
    ).fetchall()
    return [dict(r) for r in rows]


def _extract_python_dependencies(root, source: bytes) -> list[dict]:
    """Extract dependencies from a Python AST root node."""
    # Collect all function/method definitions and their line ranges
    func_ranges = []
    for child in root.children:
        if child.type == "function_definition":
            name = child.child_by_field_name("name").text.decode("utf-8")
            func_ranges.append((name, child.start_point[0], child.end_point[0]))
        elif child.type == "class_definition":
            class_name = child.child_by_field_name("name").text.decode("utf-8")
            body = child.child_by_field_name("body")
            if body:
                for body_child in body.children:
                    if body_child.type == "function_definition":
                        method_name = body_child.child_by_field_name("name").text.decode("utf-8")
                        func_ranges.append(
                            (
                                f"{class_name}.{method_name}",
                                body_child.start_point[0],
                                body_child.end_point[0],
                            )
                        )

    # Collect class inheritance
    class_bases = []
    for child in root.children:
        if child.type == "class_definition":
            class_name = child.child_by_field_name("name").text.decode("utf-8")
            superclasses = child.child_by_field_name("superclasses")
            if superclasses:
                for arg in superclasses.named_children:
                    if arg.type in ("identifier", "attribute"):
                        base_name = arg.text.decode("utf-8")
                        class_bases.append(("inherits", class_name, base_name))

    # Collect import names for matching
    import_names = set()
    for child in root.children:
        if child.type in ("import_statement", "import_from_statement"):
            for named_child in child.named_children:
                if named_child.type == "dotted_name":
                    import_names.add(named_child.text.decode("utf-8"))
                elif named_child.type == "aliased_import":
                    name = named_child.child_by_field_name("name")
                    if name:
                        import_names.add(name.text.decode("utf-8"))

    # Find all function calls in the file
    calls = []
    _collect_calls(root, calls)

    return _build_deps(calls, func_ranges, class_bases, import_names)


def _extract_js_dependencies(root, source: bytes) -> list[dict]:
    """Extract dependencies from a JavaScript AST root node."""
    func_ranges = []
    class_bases = []
    import_names = set()

    def _process_js_dep_node(node):
        """Process a single top-level JS node for dependency extraction."""
        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = name_node.text.decode("utf-8")
                func_ranges.append((name, node.start_point[0], node.end_point[0]))

        elif node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.named_children:
                if declarator.type == "variable_declarator":
                    name_node = declarator.child_by_field_name("name")
                    value_node = declarator.child_by_field_name("value")
                    if name_node and value_node and value_node.type == "arrow_function":
                        name = name_node.text.decode("utf-8")
                        func_ranges.append((name, node.start_point[0], node.end_point[0]))

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            class_name = name_node.text.decode("utf-8")

            # Extract inheritance
            for child in node.children:
                if child.type == "class_heritage":
                    for heritage_child in child.named_children:
                        if heritage_child.type in ("identifier", "member_expression"):
                            base_name = heritage_child.text.decode("utf-8")
                            class_bases.append(("inherits", class_name, base_name))

            # Extract methods
            body_node = node.child_by_field_name("body")
            if body_node:
                for body_child in body_node.named_children:
                    if body_child.type == "method_definition":
                        method_name_node = body_child.child_by_field_name("name")
                        if method_name_node:
                            method_name = method_name_node.text.decode("utf-8")
                            func_ranges.append(
                                (
                                    f"{class_name}.{method_name}",
                                    body_child.start_point[0],
                                    body_child.end_point[0],
                                )
                            )

        elif node.type == "import_statement":
            for child in node.children:
                if child.type == "import_clause":
                    _collect_js_import_names(child, import_names)

    for child in root.children:
        if child.type == "export_statement":
            for export_child in child.named_children:
                if export_child.type in (
                    "function_declaration",
                    "class_declaration",
                    "lexical_declaration",
                    "variable_declaration",
                ):
                    _process_js_dep_node(export_child)
        else:
            _process_js_dep_node(child)

    # Find all function calls in the file
    calls = []
    _collect_js_calls(root, calls)

    return _build_deps(calls, func_ranges, class_bases, import_names)


def _collect_js_import_names(import_clause, import_names: set):
    """Collect import names from a JS import_clause node into a set."""
    for child in import_clause.children:
        if child.type == "identifier":
            import_names.add(child.text.decode("utf-8"))
        elif child.type == "named_imports":
            for specifier in child.named_children:
                if specifier.type == "import_specifier":
                    name_node = specifier.child_by_field_name("name")
                    if name_node:
                        import_names.add(name_node.text.decode("utf-8"))
        elif child.type == "namespace_import":
            for ns_child in child.children:
                if ns_child.type == "identifier":
                    import_names.add(ns_child.text.decode("utf-8"))


def _collect_js_calls(node, calls: list):
    """Recursively collect all JS function call names and their line numbers."""
    if node.type == "call_expression":
        func_node = node.child_by_field_name("function")
        if func_node:
            if func_node.type == "identifier":
                calls.append((func_node.text.decode("utf-8"), node.start_point[0]))
            elif func_node.type == "member_expression":
                # e.g., axios.get() or this.db.find()
                # Extract the last property_identifier
                attr_text = func_node.text.decode("utf-8")
                parts = attr_text.split(".")
                calls.append((parts[-1], node.start_point[0]))

    for child in node.children:
        _collect_js_calls(child, calls)


def _build_deps(calls, func_ranges, class_bases, import_names) -> list[dict]:
    """Build dependency list from collected calls, func_ranges, class_bases, and import_names."""
    deps = []
    seen = set()

    for call_name, call_line in calls:
        enclosing = _find_enclosing_func(call_line, func_ranges)
        if enclosing and enclosing != call_name:
            key = (enclosing, call_name, "calls")
            if key not in seen:
                seen.add(key)
                deps.append(
                    {
                        "source": enclosing,
                        "target": call_name,
                        "dep_type": "calls",
                    }
                )

    # Append inheritance edges
    for dep_type, source, target in class_bases:
        key = (source, target, dep_type)
        if key not in seen:
            seen.add(key)
            deps.append({"source": source, "target": target, "dep_type": dep_type})

    # Append import edges
    for call_name, call_line in calls:
        if call_name in import_names:
            enclosing = _find_enclosing_func(call_line, func_ranges)
            if enclosing:
                key = (enclosing, call_name, "imports")
                if key not in seen:
                    seen.add(key)
                    deps.append({"source": enclosing, "target": call_name, "dep_type": "imports"})

    return deps


def extract_dependencies(file_path: str, language: str | None = None) -> list[dict]:
    """Extract function call dependencies from a source file.

    Returns list of dicts: {"source": "caller_name", "target": "callee_name", "dep_type": "calls"}
    """
    if language is None:
        ext = os.path.splitext(file_path)[1]
        language = get_language_for_ext(ext)
        if language is None:
            return []

    if language not in ("python", "javascript", "typescript"):
        return []  # Go implemented in later tasks

    with open(file_path, "rb") as f:
        source = f.read()

    parser = _get_parser(language)
    tree = parser.parse(source)
    root = tree.root_node

    if language == "python":
        return _extract_python_dependencies(root, source)
    elif language in ("javascript", "typescript"):
        return _extract_js_dependencies(root, source)
    else:
        return []


def _collect_calls(node, calls: list):
    """Recursively collect all function call names and their line numbers."""
    if node.type == "call":
        func_node = node.child_by_field_name("function")
        if func_node:
            if func_node.type == "identifier":
                calls.append((func_node.text.decode("utf-8"), node.start_point[0]))
            elif func_node.type == "attribute":
                # e.g., obj.method() — extract just the attribute name
                # Get the last part after the last dot
                attr_text = func_node.text.decode("utf-8")
                parts = attr_text.split(".")
                calls.append((parts[-1], node.start_point[0]))

    for child in node.children:
        _collect_calls(child, calls)


def _find_enclosing_func(line: int, func_ranges: list) -> str | None:
    """Find which function contains the given line number."""
    best = None
    best_span = float("inf")
    for name, start, end in func_ranges:
        if start <= line <= end:
            span = end - start
            if span < best_span:
                best_span = span
                best = name
    return best


def get_symbol_dependencies(db, project_id: int, symbol_name: str) -> list[dict]:
    """Get all symbols that a given symbol depends on."""
    rows = db.execute(
        """SELECT s.file_path, s.symbol_name, s.symbol_type, s.signature, d.dep_type
           FROM dependencies d
           JOIN symbols s ON d.target_id = s.id
           JOIN symbols src ON d.source_id = src.id
           WHERE src.project_id = ? AND src.symbol_name = ?""",
        (project_id, symbol_name),
    ).fetchall()
    return [dict(r) for r in rows]
