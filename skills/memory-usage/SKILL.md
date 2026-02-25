---
name: memory-usage
description: "IMPORTANT: Before searching code, reading files, or exploring the codebase, use code-memory MCP tools for persistent context. Use search() as your primary tool — it replaces recall, query_symbols, and more with unified semantic search."
---

## Code Memory — Mandatory Usage

You have persistent memory and semantic code search via the code-memory MCP server. You MUST use these tools before falling back to Grep/Glob/Read.

### Session Start (REQUIRED)

Every session, before doing anything else:
1. Call `get_project_summary` to load existing memories
2. If the response says the index is empty or stale, call `index_project`
3. If the user's request relates to existing code, call `search` with the topic

### Decision Tree for Code Exploration

**Need to find anything — functions, classes, concepts, relationships?**
→ MUST use `search("your question")` first. It searches across memories AND symbols semantically. Only use Grep if search returns no results.

**Need to understand how two things relate?**
→ MUST use `search("Thing1 Thing2")`. It auto-detects relationships via the dependency graph.

**Need to know who calls a function?**
→ Use `get_callers("symbol_name")` for exact reverse lookups. Use `search` for fuzzy/semantic queries.

**Need to trace a call path?**
→ Use `trace_call_chain("from", "to")` for exact path finding.

**Need to read actual file contents?**
→ This is fine — use Read. But only AFTER checking search first.

### Storing Context (REQUIRED)

You MUST call `remember()` after any of these events:
- **Fixed a bug** → remember the root cause and fix (e.g. "get_callers returned 0 because method calls extracted as 'method' didn't match symbol 'Class.method'")
- **Discovered how something works** → remember the mechanism (e.g. "dependencies are resolved via symbol_map in index_project_files, keyed by symbol_name")
- **Made an architectural decision** → remember the decision and rationale
- **Found a non-obvious pattern or gotcha** → remember it to avoid repeating the discovery
- **Completed a feature** → remember what was added and key implementation details

**Rule of thumb**: If you learned something that would save time in a future session, call `remember()` NOW. Don't wait — context is lost between sessions.

When calling `remember`:
- Write concise notes focused on "why" and "how", not "what files were changed"
- Link to specific files and symbols for better recall
- Memories are automatically embedded for semantic search

### What NOT to Do

- Do NOT use Grep to find function definitions — use `search`
- Do NOT use Grep to find callers — use `get_callers` or `search`
- Do NOT skip `search` when starting work on a topic you may have seen before
- Do NOT ignore the session-start checklist
