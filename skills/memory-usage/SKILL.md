---
name: memory-usage
description: "IMPORTANT: Before searching code, reading files, or exploring the codebase, use code-memory MCP tools (recall, query_symbols, get_dependencies, get_project_summary) for persistent context. These tools replace Grep/Glob/Read for understanding code structure."
---

## Code Memory — Mandatory Usage

You have persistent memory and symbol indexing via the code-memory MCP server. You MUST use these tools before falling back to Grep/Glob/Read.

### Session Start (REQUIRED)

Every session, before doing anything else:
1. Call `get_project_summary` to load existing memories
2. If the response says the index is empty or stale, call `index_project`
3. If the user's request relates to existing code, call `recall` with the topic

### Decision Tree for Code Exploration

**Need to find a function, class, or method?**
→ MUST use `query_symbols("name")` first. Only use Grep if query_symbols returns no results.

**Need to understand what a function depends on?**
→ MUST use `get_dependencies("symbol_name")`. Only read the file if you need implementation details beyond the signature.

**Need to know who calls a function?**
→ MUST use `get_callers("symbol_name")`. Do not grep for the function name.

**Need context about code you or a previous session explored?**
→ MUST use `recall("topic")` first. Only search files if recall returns nothing.

**Need to read actual file contents?**
→ This is fine — use Read. But only AFTER checking query_symbols/recall first.

### Storing Context (REQUIRED)

When you discover something important about the code:
- Call `remember` with concise notes focused on "why" and "how"
- Link to specific files and symbols for better recall
- Check with `recall` first to avoid duplicates

### What NOT to Do

- Do NOT use Grep to find function definitions — use `query_symbols`
- Do NOT use Grep to find callers — use `get_callers`
- Do NOT skip `recall` when starting work on a topic you may have seen before
- Do NOT ignore the session-start checklist
