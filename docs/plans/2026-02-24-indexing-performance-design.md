# Indexing Performance Improvements

**Date:** 2026-02-24
**Status:** Approved

## Problem

`index_project()` has three compounding performance issues:
1. Re-parses all files even when most are unchanged
2. Parses every file twice (once for symbols, once for dependencies)
3. Does N+1 database queries when inserting dependencies

A 1000-file project takes 20-40 seconds to index. Re-indexing after changing 5 files takes the same 20-40 seconds.

## Design

### 1. Incremental Indexing

Use git to detect changed files since the last index.

- On `index_project()`, read `project.last_indexed_commit` from DB
- If set, run `git diff --name-only <last_commit> HEAD -- '*.py'` to get changed files
- Parse and index only those files (delete their old symbols/deps first, re-insert)
- Update `last_indexed_commit` to current HEAD after indexing
- First run (no last commit): full index as before
- No changes since last index: skip entirely, return early
- Deleted files: remove their symbols from DB, don't parse

**New function:** `git_utils.get_changed_files(repo_path, since_commit, extension=".py")`

### 2. Single-Pass Parsing

Merge `index_project_symbols()` and `build_project_dependencies()` into a unified `index_project_files()`.

- Walk the project once instead of twice
- Parse each file once with a cached parser singleton
- Extract both symbols and dependencies from the same parse tree
- `_make_parser()` becomes a module-level cached instance

### 3. Batched DB Writes for Dependencies

Replace N+1 symbol ID lookups with a single bulk query.

- After inserting all symbols, load the full name-to-ID map in one query
- Look up source/target IDs via dict (nanoseconds vs milliseconds)
- Insert all dependencies with `executemany()` + single `commit()`

## Files Changed

| File | Changes |
|------|---------|
| `git_utils.py` | Add `get_changed_files()` |
| `symbol_indexer.py` | Cache parser; merge into `index_project_files()`; batch dependency inserts |
| `mcp_tools.py` | Call `index_project_files()` instead of two separate functions |
| `db.py` | Add helper to update `last_indexed_commit` |
| Tests | Update existing, add incremental + single-pass tests |

## Expected Results

| Scenario | Before | After |
|----------|--------|-------|
| Re-index (5/1000 files changed) | 20-40s | <1s |
| First full index (1000 files) | 20-40s | 10-15s |
| Dependency insertion (2500 deps) | 5000 queries | 1 query + 1 executemany |

## Constraints

- All 7 MCP tool signatures remain unchanged
- Database schema unchanged (`last_indexed_commit` column already exists)
- Recall/query behavior untouched
