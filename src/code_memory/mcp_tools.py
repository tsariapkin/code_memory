from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from src.code_memory.db import Database, default_db_path
from src.code_memory.graph_engine import CodeGraph
from src.code_memory.memory_manager import MemoryManager
from src.code_memory.symbol_indexer import (
    index_project_files,
    query_symbol,
)
from src.code_memory.usage_logger import log_tool_usage

mcp = FastMCP("code-memory")

_manager: MemoryManager | None = None
_graph: CodeGraph | None = None


def _get_graph() -> CodeGraph:
    global _graph
    if _graph is None:
        _graph = CodeGraph()
    return _graph


def _ensure_graph_loaded() -> CodeGraph:
    graph = _get_graph()
    if not graph.is_loaded:
        manager = _get_manager()
        graph.build_from_db(manager.db, manager.project_id)
    return graph


def _get_manager() -> MemoryManager:
    global _manager
    if _manager is None:
        project_root = os.getcwd()
        db_path = default_db_path(project_root)
        db = Database(db_path)
        db.initialize()
        _manager = MemoryManager(db, project_root)
    return _manager


@mcp.tool(
    name="remember",
    title="Remember",
    description=(
        "Use when you learn something important about the code."
        " Stores a note optionally linked to a file/symbol."
    ),
)
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
    log_tool_usage(
        manager.db, manager.project_id, "remember", f"notes={notes[:50]}", result_empty=False
    )
    return f"Stored memory #{memory_id}{symbol_msg}"


@mcp.tool(
    name="recall",
    title="Recall",
    description=(
        "Use when you need context about code you've seen before."
        " Searches memories by symbol, file path, or keyword."
    ),
)
def recall(query: str) -> str:
    """Search memories by symbol name, file path, or keyword.

    Returns matching memories with staleness flags.

    Args:
        query: Search term — a symbol name, file path, or keyword
    """
    manager = _get_manager()
    results = manager.recall(query)
    if not results:
        log_tool_usage(
            manager.db, manager.project_id, "recall", f"query={query}", result_empty=True
        )
        return "No memories found."

    lines = []
    for m in results:
        stale_flag = " [STALE]" if m["is_stale"] else ""
        symbol = f" ({m['symbol_name']})" if m["symbol_name"] else ""
        file_info = f" in {m['file_path']}" if m["file_path"] else ""
        lines.append(f"#{m['id']}{stale_flag}{file_info}{symbol}: {m['notes']}")
    log_tool_usage(manager.db, manager.project_id, "recall", f"query={query}", result_empty=False)
    return "\n".join(lines)


@mcp.tool(
    name="get_project_summary",
    title="Project Summary",
    description=(
        "Use when starting a session to load existing context."
        " Shows memory counts and recent memories."
    ),
)
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
    log_tool_usage(manager.db, manager.project_id, "get_project_summary", "", result_empty=False)
    return "\n".join(lines)


@mcp.tool(
    name="forget",
    title="Forget",
    description=("Use when a memory is outdated or incorrect." " Deletes a memory by its ID."),
)
def forget(memory_id: int) -> str:
    """Delete a memory by its ID. Use this to remove outdated or incorrect memories.

    Args:
        memory_id: The memory ID to delete (shown as #N in recall output)
    """
    manager = _get_manager()
    found = manager.forget(memory_id)
    log_tool_usage(
        manager.db, manager.project_id, "forget", f"id={memory_id}", result_empty=not found
    )
    if found:
        return f"Deleted memory #{memory_id}"
    return f"Memory #{memory_id} not found."


@mcp.tool(
    name="index_project",
    title="Index Project",
    description=(
        "Use when starting on a new project or after major refactors."
        " Parses Python, JavaScript/TypeScript, and Go files"
        " to extract symbols and dependencies."
    ),
)
def index_project() -> str:
    """Index all source files (Python, JS/TS, Go) in the current project.

    Extracts functions, classes, methods, imports, and their dependencies.
    Run this when starting work on a new project or after major refactors.
    """
    from src.code_memory.git_utils import get_changed_files, get_current_commit

    manager = _get_manager()
    db = manager.db
    project_id = manager.project_id
    project_root = manager.project_root

    # Check for incremental indexing
    last_commit = db.get_last_indexed_commit(project_id)
    changed_files = None

    if last_commit:
        current = get_current_commit(project_root)
        if current == last_commit:
            _get_graph().invalidate()
            log_tool_usage(manager.db, manager.project_id, "index_project", "", result_empty=False)
            return "No changes since last index."
        changed_files = get_changed_files(project_root, last_commit)
        if not changed_files:
            _get_graph().invalidate()
            log_tool_usage(manager.db, manager.project_id, "index_project", "", result_empty=False)
            return "No source files changed since last index."

    sym_count, dep_count = index_project_files(db, project_id, project_root, changed_files)

    # Update last indexed commit
    current_commit = get_current_commit(project_root)
    db.update_last_indexed_commit(project_id, current_commit)

    _get_graph().invalidate()
    log_tool_usage(manager.db, manager.project_id, "index_project", "", result_empty=False)
    if changed_files:
        return (
            f"Incremental index: {sym_count} symbols and"
            f" {dep_count} dependencies in {len(changed_files)} files."
        )
    return f"Indexed {sym_count} symbols and {dep_count} dependencies."


@mcp.tool(
    name="query_symbols",
    title="Query Symbols",
    description=(
        "Use when you need to find a function, class, or method."
        " Looks up symbols by name with signatures and locations."
    ),
)
def query_symbols(name: str) -> str:
    """Look up symbols (functions, classes, methods) by name.

    Returns signatures and locations — not entire files.

    Args:
        name: Symbol name or partial match (e.g. "login", "UserService")
    """
    manager = _get_manager()
    results = query_symbol(manager.db, manager.project_id, name)
    if not results:
        log_tool_usage(
            manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=True
        )
        return f"No symbols found matching '{name}'. Try running index_project first."

    lines = []
    for s in results:
        lines.append(
            f"{s['symbol_type']} {s['symbol_name']}"
            f" in {s['file_path']}:{s['line_start']}-{s['line_end']}"
        )
        if s.get("signature"):
            lines.append(f"  {s['signature']}")
    log_tool_usage(
        manager.db, manager.project_id, "query_symbols", f"name={name}", result_empty=False
    )
    return "\n".join(lines)


@mcp.tool(
    name="get_dependencies",
    title="Get Dependencies",
    description=(
        "Use when you need to understand what a symbol depends on."
        " Lists calls, imports, and inheritance."
    ),
)
def get_dependencies(symbol_name: str) -> str:
    """List what a symbol depends on (calls, imports, inherits).

    Helps understand code flow without reading entire files.

    Args:
        symbol_name: Exact symbol name (e.g. "login", "UserService.get_user")
    """
    graph = _ensure_graph_loaded()
    manager = _get_manager()
    deps = graph.get_dependencies(symbol_name)
    if not deps:
        log_tool_usage(
            manager.db,
            manager.project_id,
            "get_dependencies",
            f"symbol={symbol_name}",
            result_empty=True,
        )
        return f"No dependencies found for '{symbol_name}'."

    lines = [f"Dependencies of {symbol_name}:"]
    for d in deps:
        lines.append(
            f"  {d['dep_type']} {d['symbol_name']} ({d['symbol_type']}) in {d['file_path']}"
        )
        if d.get("signature"):
            lines.append(f"    {d['signature']}")
    log_tool_usage(
        manager.db,
        manager.project_id,
        "get_dependencies",
        f"symbol={symbol_name}",
        result_empty=False,
    )
    return "\n".join(lines)


@mcp.tool(
    name="get_callers",
    title="Get Callers",
    description=(
        "Use when you need to assess impact of changing a symbol."
        " Finds what calls or imports it."
    ),
)
def get_callers(symbol_name: str) -> str:
    """List what calls or imports a symbol (reverse dependency lookup).

    Useful for understanding impact of changes — "who will break if I change this?"

    Args:
        symbol_name: Exact symbol name (e.g. "validate", "UserService.login")
    """
    graph = _ensure_graph_loaded()
    manager = _get_manager()
    callers = graph.get_callers(symbol_name)
    if not callers:
        log_tool_usage(
            manager.db,
            manager.project_id,
            "get_callers",
            f"symbol={symbol_name}",
            result_empty=True,
        )
        return f"No callers found for '{symbol_name}'."

    lines = [f"Callers of {symbol_name}:"]
    for c in callers:
        lines.append(
            f"  {c['dep_type']} from {c['symbol_name']} ({c['symbol_type']}) in {c['file_path']}"
        )
        if c.get("signature"):
            lines.append(f"    {c['signature']}")
    log_tool_usage(
        manager.db, manager.project_id, "get_callers", f"symbol={symbol_name}", result_empty=False
    )
    return "\n".join(lines)


@mcp.tool(
    name="trace_call_chain",
    title="Trace Call Chain",
    description=(
        "Use when you need to trace how a request flows through code."
        " Finds all call paths between two symbols."
    ),
)
def trace_call_chain(from_symbol: str, to_symbol: str, max_depth: int = 5) -> str:
    """Find call chains between two symbols (multi-hop traversal).

    Shows all paths from one function to another through the call graph.
    Useful for understanding how a request flows from endpoint to database.

    Args:
        from_symbol: Starting symbol name
        to_symbol: Target symbol name
        max_depth: Maximum chain length (default 5)
    """
    max_depth = min(max_depth, 20)
    graph = _ensure_graph_loaded()
    manager = _get_manager()
    chains = graph.trace_call_chain(from_symbol, to_symbol, max_depth)
    if not chains:
        log_tool_usage(
            manager.db,
            manager.project_id,
            "trace_call_chain",
            f"from={from_symbol} to={to_symbol}",
            result_empty=True,
        )
        return f"No call chain found from '{from_symbol}' to '{to_symbol}' (max depth {max_depth})."

    lines = [f"Call chains from {from_symbol} to {to_symbol}:"]
    for i, chain in enumerate(chains, 1):
        lines.append(f"  {i}. {' -> '.join(chain)}")
    log_tool_usage(
        manager.db,
        manager.project_id,
        "trace_call_chain",
        f"from={from_symbol} to={to_symbol}",
        result_empty=False,
    )
    return "\n".join(lines)
