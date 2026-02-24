#!/bin/sh
cat <<'EOF'
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "You have code-memory MCP tools available. Before using Grep/Glob/Read to explore code, first try: recall(query) for past context, query_symbols(name) for function/class signatures, get_dependencies(symbol_name) for call graphs. Use remember() to persist important discoveries for future sessions."
  }
}
EOF
