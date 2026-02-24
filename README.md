# Code-memory

A Claude Code plugin that gives Claude persistent memory and symbol-level code indexing across sessions. Memories are linked to files and symbols, with automatic staleness detection via git.

## Installation

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

### Via Claude Code marketplace (recommended)

Add the marketplace and install:

```
/plugin marketplace add tsariapkin/code-memory
/plugin install code-memory@code-memory-marketplace
```

> **Note:** Claude Code does not auto-install Python dependencies. After installing, run `uv sync` in the plugin's cached directory (`~/.claude/plugins/cache/code-memory/`).

### Manual setup

Clone the repo and install dependencies:

```bash
git clone https://github.com/tsariapkin/code-memory.git ~/.claude/plugins/code-memory
cd ~/.claude/plugins/code-memory
uv sync
```

Then add the MCP server to your project's `.mcp.json` (or `~/.claude/.mcp.json` for global use):

```json
{
  "mcpServers": {
    "code-memory": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--project", "/path/to/code-memory", "python", "-m", "src.code_memory"]
    }
  }
}
```

Replace `/path/to/code-memory` with the actual path (e.g. `~/.claude/plugins/code-memory`).

## Tools

The plugin exposes 7 MCP tools:

| Tool | Description |
|------|-------------|
| `remember(notes, file_path?, symbol_name?, line?)` | Store a memory, optionally linked to a file/symbol. If `file_path` and `line` are given, the enclosing symbol is auto-resolved. |
| `recall(query)` | Search memories by symbol name, file path, or keyword. Stale memories are flagged. |
| `get_project_summary()` | Overview of total/stale memory counts and recent memories. |
| `forget(memory_id)` | Delete a memory by ID. |
| `index_project()` | Parse all Python files — extracts functions, classes, methods, imports, and builds a dependency graph. |
| `query_symbols(name)` | Look up symbols by name (partial match). Returns signatures and locations. |
| `get_dependencies(symbol_name)` | List what a symbol calls or imports. |

## Usage

### Session start

Call `get_project_summary` to load existing context. On a new project or after major refactors, call `index_project` to build the symbol index.

### Storing memories

```
remember(
    notes="Validates JWT against Redis, returns user dict",
    file_path="src/auth.py",
    symbol_name="UserService.login"
)
```

Or let the symbol auto-resolve from a line number:

```
remember(notes="Complex retry logic here", file_path="src/client.py", line=42)
```

### Recalling context

```
recall("UserService")       # search by symbol
recall("auth.py")           # search by file
recall("JWT")               # search by keyword
```

Memories that refer to files changed since they were stored are marked `[STALE]`.

### Symbol queries

```
query_symbols("login")              # find symbols by name
get_dependencies("UserService.login")  # see what it calls/imports
```

These return signatures and locations without reading entire files.

## How it works

- **Storage**: SQLite database per project, stored in `~/.code-memory/`. Each project is identified by a SHA-256 hash of its root path.
- **Staleness**: When a memory is stored, the current git commit hash is saved. On recall, if the linked file has changed since that commit, the memory is flagged as stale.
- **Symbol indexing**: Uses [tree-sitter](https://tree-sitter.github.io/) to parse Python files into functions, classes, methods, and imports. Dependency tracking maps function calls to their definitions.

## Development

```bash
uv sync --all-extras
uv run pytest
```