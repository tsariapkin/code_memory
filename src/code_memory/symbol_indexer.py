from __future__ import annotations

import hashlib
import os

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())

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


_parser: Parser | None = None


def _get_parser() -> Parser:
    global _parser
    if _parser is None:
        _parser = Parser(PY_LANGUAGE)
    return _parser


def _content_hash(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()[:16]


def _extract_signature(node) -> str:
    """Extract the first line of a function/class definition as its signature."""
    text = node.text.decode("utf-8")
    first_line = text.split("\n")[0]
    return first_line.rstrip(":")


def parse_file_symbols(file_path: str) -> list[dict]:
    """Parse a Python file and extract all symbols (functions, classes, methods, imports).

    Returns a list of dicts with keys:
        symbol_name, symbol_type, line_start, line_end, signature, content_hash
    """
    with open(file_path, "rb") as f:
        source = f.read()

    parser = _get_parser()
    tree = parser.parse(source)
    root = tree.root_node

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


def _collect_python_files(
    project_root: str, only_files: list[str] | None = None
) -> list[tuple[str, str]]:
    """Collect (full_path, rel_path) pairs for Python files.

    If only_files is given, return only those relative paths (that exist).
    """
    if only_files is not None:
        result = []
        for rel in only_files:
            full = os.path.join(project_root, rel)
            if rel.endswith(".py") and os.path.isfile(full):
                result.append((full, rel))
        return result

    result = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        # Prune skipped directories in-place
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, project_root)
            result.append((full_path, rel_path))
    return result


def index_project_files(
    db, project_id: int, project_root: str, changed_files: list[str] | None = None
) -> tuple[int, int]:
    """Parse Python files and store symbols + dependencies in one pass.

    If changed_files is provided, only index those files (incremental mode).
    Returns (symbol_count, dependency_count).
    """
    files = _collect_python_files(project_root, changed_files)

    if changed_files is not None:
        # Delete old symbols and deps for changed files
        for _, rel_path in files:
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
            if rel.endswith(".py"):
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

    for full_path, rel_path in files:
        try:
            symbols = parse_file_symbols(full_path)
        except Exception:
            continue

        for sym in symbols:
            db.execute(
                """INSERT OR REPLACE INTO symbols
                   (project_id, file_path, symbol_name, symbol_type,
                    line_start, line_end, signature, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    rel_path,
                    sym["symbol_name"],
                    sym["symbol_type"],
                    sym["line_start"],
                    sym["line_end"],
                    sym["signature"],
                    sym["content_hash"],
                ),
            )
            sym_count += 1

        try:
            deps = extract_dependencies(full_path)
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


def extract_dependencies(file_path: str) -> list[dict]:
    """Extract function call dependencies from a Python file.

    Returns list of dicts: {"source": "caller_name", "target": "callee_name", "dep_type": "calls"}
    """
    with open(file_path, "rb") as f:
        source = f.read()

    parser = _get_parser()
    tree = parser.parse(source)
    root = tree.root_node

    # First, collect all function/method definitions and their line ranges
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

    # Find all function calls in the file
    calls = []
    _collect_calls(root, calls)

    # Map each call to its enclosing function
    deps = []
    seen = set()
    for call_name, call_line in calls:
        enclosing = _find_enclosing_func(call_line, func_ranges)
        if enclosing and enclosing != call_name:
            key = (enclosing, call_name)
            if key not in seen:
                seen.add(key)
                deps.append(
                    {
                        "source": enclosing,
                        "target": call_name,
                        "dep_type": "calls",
                    }
                )

    return deps


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
