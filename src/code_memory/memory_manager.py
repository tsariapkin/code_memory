from src.code_memory.db import Database
from src.code_memory.git_utils import get_current_commit, has_file_changed


class MemoryManager:
    def __init__(self, db: Database, project_root: str):
        self.db = db
        self.project_root = project_root
        self.project_id = db.get_or_create_project(project_root)

    def remember(
        self,
        notes: str,
        file_path: str | None = None,
        symbol_name: str | None = None,
    ) -> int:
        commit_hash = get_current_commit(self.project_root)
        cursor = self.db.execute(
            """INSERT INTO memories (project_id, file_path, symbol_name, notes, commit_hash)
               VALUES (?, ?, ?, ?, ?)""",
            (self.project_id, file_path, symbol_name, notes, commit_hash),
        )
        self.db.conn.commit()
        return cursor.lastrowid

    def recall(self, query: str) -> list[dict]:
        rows = self.db.execute(
            """SELECT id, file_path, symbol_name, notes, commit_hash, is_stale,
                      created_at, updated_at
               FROM memories
               WHERE project_id = ?
                 AND (symbol_name LIKE ? OR file_path LIKE ? OR notes LIKE ?)
               ORDER BY updated_at DESC""",
            (self.project_id, f"%{query}%", f"%{query}%", f"%{query}%"),
        ).fetchall()

        results = []
        for row in rows:
            memory = dict(row)
            memory["is_stale"] = bool(memory["is_stale"])
            # Check staleness
            if memory["file_path"] and memory["commit_hash"]:
                stale = has_file_changed(
                    self.project_root, memory["file_path"], memory["commit_hash"]
                )
                if stale and not memory["is_stale"]:
                    self.db.execute(
                        "UPDATE memories SET is_stale = TRUE WHERE id = ?",
                        (memory["id"],),
                    )
                    self.db.conn.commit()
                    memory["is_stale"] = True
            results.append(memory)
        return results

    def forget(self, memory_id: int) -> bool:
        cursor = self.db.execute(
            "DELETE FROM memories WHERE id = ? AND project_id = ?",
            (memory_id, self.project_id),
        )
        self.db.conn.commit()
        return cursor.rowcount > 0

    def get_project_summary(self) -> dict:
        total = self.db.execute(
            "SELECT COUNT(*) FROM memories WHERE project_id = ?",
            (self.project_id,),
        ).fetchone()[0]

        stale = self.db.execute(
            "SELECT COUNT(*) FROM memories WHERE project_id = ? AND is_stale = TRUE",
            (self.project_id,),
        ).fetchone()[0]

        recent = self.db.execute(
            """SELECT id, file_path, symbol_name, notes, is_stale, created_at
               FROM memories
               WHERE project_id = ?
               ORDER BY updated_at DESC
               LIMIT 10""",
            (self.project_id,),
        ).fetchall()

        return {
            "project_root": self.project_root,
            "total_memories": total,
            "stale_memories": stale,
            "recent_memories": [dict(r) for r in recent],
        }
