from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from src.code_memory.db import Database, default_db_path
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import (
    build_project_dependencies,
    get_symbol_dependencies,
    index_project_symbols,
    query_symbol,
)

mcp = FastMCP("code-memory")

_manager: MemoryManager | None = None


def _get_manager() -> MemoryManager:
    global _manager
    if _manager is None:
        project_root = os.getcwd()
        db_path = default_db_path(project_root)
        db = Database(db_path)
        db.initialize()
        _manager = MemoryManager(db, project_root)
    return _manager


@mcp.tool()
def remember(
    notes: str,
    file_path: str | None = None,
    symbol_name: str | None = None,
    line: int | None = None,
) -> str:
    """Store a memory about code. Link it to a file and/or symbol for later recall.

    Args:
        notes: What to remember (e.g. "uses JWT, validates against Redis")
        file_path: Optional file path (e.g. "src/auth.py")
        symbol_name: Optional symbol name (e.g. "UserService.login").
            If not provided but file_path and line are given,
            auto-resolves to the enclosing function/class.
        line: Optional line number. Used with file_path to auto-resolve the enclosing symbol.
    """
    manager = _get_manager()

    # Auto-resolve symbol from file + line
    if file_path and line and not symbol_name:
        full_path = os.path.join(manager.project_root, file_path)
        if os.path.exists(full_path):
            from src.code_memory.symbol_indexer import find_enclosing_symbol

            symbol_name = find_enclosing_symbol(full_path, line)

    memory_id = manager.remember(notes=notes, file_path=file_path, symbol_name=symbol_name)
    symbol_msg = f" (linked to {symbol_name})" if symbol_name else ""
    return f"Stored memory #{memory_id}{symbol_msg}"


@mcp.tool()
def recall(query: str) -> str:
    """Search memories by symbol name, file path, or keyword.

    Returns matching memories with staleness flags.

    Args:
        query: Search term — a symbol name, file path, or keyword
    """
    manager = _get_manager()
    results = manager.recall(query)
    if not results:
        return "No memories found."

    lines = []
    for m in results:
        stale_flag = " [STALE]" if m["is_stale"] else ""
        symbol = f" ({m['symbol_name']})" if m["symbol_name"] else ""
        file_info = f" in {m['file_path']}" if m["file_path"] else ""
        lines.append(f"#{m['id']}{stale_flag}{file_info}{symbol}: {m['notes']}")
    return "\n".join(lines)


@mcp.tool()
def get_project_summary() -> str:
    """Get an overview of the current project's memories. Call this at the start of each session."""
    manager = _get_manager()
    summary = manager.get_project_summary()

    lines = [
        f"Project: {summary['project_root']}",
        f"Total memories: {summary['total_memories']}",
        f"Stale memories: {summary['stale_memories']}",
        "",
        "Recent memories:",
    ]
    for m in summary["recent_memories"]:
        stale_flag = " [STALE]" if m["is_stale"] else ""
        symbol = f" ({m['symbol_name']})" if m["symbol_name"] else ""
        file_info = f" in {m['file_path']}" if m["file_path"] else ""
        lines.append(f"  #{m['id']}{stale_flag}{file_info}{symbol}: {m['notes']}")

    if not summary["recent_memories"]:
        lines.append("  (none yet)")
    return "\n".join(lines)


@mcp.tool()
def forget(memory_id: int) -> str:
    """Delete a memory by its ID. Use this to remove outdated or incorrect memories.

    Args:
        memory_id: The memory ID to delete (shown as #N in recall output)
    """
    manager = _get_manager()
    if manager.forget(memory_id):
        return f"Deleted memory #{memory_id}"
    return f"Memory #{memory_id} not found."


@mcp.tool()
def index_project() -> str:
    """Index all Python files in the current project.

    Extracts functions, classes, methods, imports, and their dependencies.
    Run this when starting work on a new project or after major refactors.
    """
    manager = _get_manager()
    db = manager.db
    project_id = manager.project_id
    project_root = manager.project_root

    sym_count = index_project_symbols(db, project_id, project_root)
    dep_count = build_project_dependencies(db, project_id, project_root)
    return f"Indexed {sym_count} symbols and {dep_count} dependencies."


@mcp.tool()
def query_symbols(name: str) -> str:
    """Look up symbols (functions, classes, methods) by name.

    Returns signatures and locations — not entire files.

    Args:
        name: Symbol name or partial match (e.g. "login", "UserService")
    """
    manager = _get_manager()
    results = query_symbol(manager.db, manager.project_id, name)
    if not results:
        return f"No symbols found matching '{name}'. Try running index_project first."

    lines = []
    for s in results:
        lines.append(
            f"{s['symbol_type']} {s['symbol_name']}"
            f" in {s['file_path']}:{s['line_start']}-{s['line_end']}"
        )
        if s.get("signature"):
            lines.append(f"  {s['signature']}")
    return "\n".join(lines)


@mcp.tool()
def get_dependencies(symbol_name: str) -> str:
    """List what a symbol depends on (calls, imports).

    Helps understand code flow without reading entire files.

    Args:
        symbol_name: Exact symbol name (e.g. "login", "UserService.get_user")
    """
    manager = _get_manager()
    deps = get_symbol_dependencies(manager.db, manager.project_id, symbol_name)
    if not deps:
        return f"No dependencies found for '{symbol_name}'."

    lines = [f"Dependencies of {symbol_name}:"]
    for d in deps:
        lines.append(
            f"  {d['dep_type']} {d['symbol_name']} ({d['symbol_type']}) in {d['file_path']}"
        )
        if d.get("signature"):
            lines.append(f"    {d['signature']}")
    return "\n".join(lines)
