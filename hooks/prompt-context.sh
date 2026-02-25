#!/bin/sh
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "You have code-memory MCP tools available. Before using Grep/Glob/Read to explore code, first try: recall(query) for past context, query_symbols(name) for function/class signatures, get_dependencies(symbol_name) for call graphs. IMPORTANT: After completing a task, fixing a bug, or discovering how something works, call remember() to persist the insight. Examples: architectural decisions, bug root causes, non-obvious patterns, gotchas. If you learned something that would save time next session, remember it NOW."
  }
}
EOF
