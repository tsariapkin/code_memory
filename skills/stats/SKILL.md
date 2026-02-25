---
name: stats
description: Show code-memory tool usage statistics
argument-hint: [days]
disable-model-invocation: true
---

Call the `get_usage_stats` MCP tool with days=$ARGUMENTS (default 7 if not provided).

Present the results clearly, showing call counts and empty-result rates per tool.
