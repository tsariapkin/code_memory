---
name: memory-usage
description: "IMPORTANT: Before searching code, reading files, or exploring the codebase, use code-memory MCP tools (recall, query_symbols, get_dependencies, get_project_summary) for persistent context. These tools replace Grep/Glob/Read for understanding code structure."
---

## Code Memory

You have access to persistent memory and symbol indexing tools via the code-memory MCP server.

### Session Start

1. Call `get_project_summary` to see existing memories
2. If this is a new project or after major refactors, call `index_project` to build the symbol index

### Symbol Queries (Instead of Reading Whole Files)

- Use `query_symbols("ClassName")` to get signatures and locations — much cheaper than reading entire files
- Use `get_dependencies("function_name")` to understand what a function calls without tracing through code manually
- Only read full files when you need implementation details beyond the signature

### Memory Management

- When you discover important context, call `remember` with:
  - `notes`: what you learned
  - `file_path`: the relevant file (if any)
  - `symbol_name`: the relevant function/class (if any)
  - `line`: if you know the line number, the symbol is auto-resolved
- Before exploring previously-seen code, call `recall` with the topic
- If a memory is marked `[STALE]`, re-investigate and update it

### Guidelines

- Keep notes concise — focus on "why" and "how", not raw code
- Link memories to specific symbols for better recall
- Check with `recall` before creating duplicate memories
- Re-index with `index_project` after large refactors
