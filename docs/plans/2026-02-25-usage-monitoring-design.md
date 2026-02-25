# Design: Increase & Monitor Code-Memory Plugin Usage

**Date**: 2025-02-25
**Problem**: Code-memory MCP tools are installed and indexed in target repos but Claude still defaults to Grep/Glob/Read. When tools are called, empty results reinforce avoidance.

**Root causes**:
1. Nudges are advisory, not directive — Claude treats "try code-memory first" as optional
2. Built-in tools (Grep/Glob/Read) have zero friction; MCP tools feel foreign
3. Empty results on first attempt kill future usage in a session

## 1. Usage Logging (Observability)

New SQLite table `tool_usage` in the existing per-project database:

| Column | Type | Purpose |
|--------|------|---------|
| id | INTEGER PK | Auto-increment |
| tool_name | TEXT | e.g. "recall", "query_symbols" |
| project_id | TEXT | Which project |
| timestamp | REAL | Unix timestamp |
| args_summary | TEXT | Truncated args for context |
| result_empty | BOOLEAN | Did the tool return no results? |

New MCP tool `get_usage_stats(days?)` returns a summary:
```
Last 7 days:
  recall: 12 calls (3 empty)
  query_symbols: 8 calls (1 empty)
  remember: 4 calls
  index_project: 1 call
  get_dependencies: 0 calls
```

Implementation: a decorator/wrapper around each existing tool function. No changes to tool logic.

## 2. Stronger Nudges

### memory-usage skill rewrite

Current text is advisory. New text must:
- Use mandatory language: "You MUST call `recall` or `query_symbols` BEFORE using Grep/Glob/Read"
- Include a decision tree: symbol lookup → `query_symbols`, context recall → `recall`, file contents → only then `Read`
- Provide concrete examples of when each tool wins over Grep

### UserPromptSubmit hook text

Same shift from advisory to directive. Match the skill language.

## 3. Auto-Bootstrap on Empty State

### get_project_summary enhancement

When the index is empty or stale (last indexed commit behind HEAD), append:
```
Symbol index is empty/stale. Run index_project to populate it.
```

### Empty-result guidance

When `recall`, `get_dependencies`, or `get_callers` return no results, check if the index exists and suggest indexing. (`query_symbols` already does this — extend the pattern.)

## 4. Session-Start Checklist

Update `memory-usage` skill to enforce a session-start sequence:
1. Call `get_project_summary`
2. If index is empty/stale → call `index_project`
3. If memories exist → call `recall` with the current task topic

This ensures every session starts with populated data.

## Out of Scope

- No hook-based interception of Grep/Glob (fragile)
- No changes to existing tool signatures or return formats beyond additions above
- No external dashboards — `get_usage_stats` is the monitoring interface