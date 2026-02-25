import hashlib
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id INTEGER PRIMARY KEY,
    root_path TEXT UNIQUE NOT NULL,
    last_indexed_commit TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    file_path TEXT,
    symbol_name TEXT,
    notes TEXT NOT NULL,
    commit_hash TEXT,
    is_stale BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memories_symbol ON memories(project_id, symbol_name);
CREATE INDEX IF NOT EXISTS idx_memories_file ON memories(project_id, file_path);

CREATE TABLE IF NOT EXISTS symbols (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_type TEXT NOT NULL,
    language TEXT DEFAULT 'python',
    line_start INTEGER,
    line_end INTEGER,
    signature TEXT,
    content_hash TEXT,
    UNIQUE(project_id, file_path, symbol_name)
);

CREATE TABLE IF NOT EXISTS dependencies (
    source_id INTEGER REFERENCES symbols(id),
    target_id INTEGER REFERENCES symbols(id),
    dep_type TEXT,
    PRIMARY KEY (source_id, target_id, dep_type)
);

CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(project_id, file_path);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(project_id, symbol_name);
CREATE INDEX IF NOT EXISTS idx_deps_type ON dependencies(dep_type);

CREATE TABLE IF NOT EXISTS tool_usage (
    id INTEGER PRIMARY KEY,
    tool_name TEXT NOT NULL,
    project_id INTEGER REFERENCES project(id),
    timestamp REAL NOT NULL,
    args_summary TEXT,
    result_empty BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_tool_usage_project ON tool_usage(project_id, timestamp);

CREATE TABLE IF NOT EXISTS embeddings (
    id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project(id),
    source_type TEXT NOT NULL,
    source_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    vector BLOB NOT NULL,
    UNIQUE(project_id, source_type, source_id)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_project ON embeddings(project_id, source_type);
"""


def default_db_path(project_root: str) -> str:
    """Return the default DB path for a project: ~/.code-memory/<hash>.db"""
    path_hash = hashlib.sha256(project_root.encode()).hexdigest()[:16]
    db_dir = Path.home() / ".code-memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / f"{path_hash}.db")


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._conn

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def get_or_create_project(self, root_path: str) -> int:
        row = self.execute("SELECT id FROM project WHERE root_path = ?", (root_path,)).fetchone()
        if row:
            return row[0]
        cursor = self.execute("INSERT INTO project (root_path) VALUES (?)", (root_path,))
        self.conn.commit()
        return cursor.lastrowid

    def get_last_indexed_commit(self, project_id: int) -> str | None:
        row = self.execute(
            "SELECT last_indexed_commit FROM project WHERE id = ?",
            (project_id,),
        ).fetchone()
        return row[0] if row else None

    def update_last_indexed_commit(self, project_id: int, commit_hash: str) -> None:
        self.execute(
            "UPDATE project SET last_indexed_commit = ? WHERE id = ?",
            (commit_hash, project_id),
        )
        self.conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
