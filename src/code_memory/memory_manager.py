from __future__ import annotations

import logging

from src.code_memory.db import Database
from src.code_memory.git_utils import get_current_commit, has_file_changed

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, db: Database, project_root: str, embedding_engine=None):
        self.db = db
        self.project_root = project_root
        self.project_id = db.get_or_create_project(project_root)
        self._embedding_engine = embedding_engine

    def _build_memory_text(self, notes: str, file_path: str | None, symbol_name: str | None) -> str:
        parts = [notes]
        if symbol_name:
            parts.append(symbol_name)
        if file_path:
            parts.append(file_path)
        return " ".join(parts)

    def _store_embedding(self, source_type: str, source_id: int, text: str) -> None:
        if self._embedding_engine is None:
            return
        try:
            self._embedding_engine.ensure_ready()
            vec = self._embedding_engine.embed(text)
            blob = self._embedding_engine.vector_to_blob(vec)
            self.db.execute(
                """INSERT OR REPLACE INTO embeddings
                   (project_id, source_type, source_id, text, vector)
                   VALUES (?, ?, ?, ?, ?)""",
                (self.project_id, source_type, source_id, text, blob),
            )
            self.db.conn.commit()
        except Exception:
            logger.warning("Failed to store embedding for %s #%d", source_type, source_id)

    def _delete_embedding(self, source_type: str, source_id: int) -> None:
        self.db.execute(
            "DELETE FROM embeddings WHERE project_id = ? AND source_type = ? AND source_id = ?",
            (self.project_id, source_type, source_id),
        )
        self.db.conn.commit()

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
        memory_id = cursor.lastrowid
        text = self._build_memory_text(notes, file_path, symbol_name)
        self._store_embedding("memory", memory_id, text)
        return memory_id

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
        if cursor.rowcount > 0:
            self._delete_embedding("memory", memory_id)
            return True
        return False

    def semantic_search(
        self, query: str, top_k: int = 10, source_type: str | None = None
    ) -> list[dict]:
        if self._embedding_engine is None:
            return []
        try:
            self._embedding_engine.ensure_ready()
        except Exception:
            return []

        import numpy as np

        type_filter = ""
        params: list = [self.project_id]
        if source_type:
            type_filter = " AND source_type = ?"
            params.append(source_type)

        rows = self.db.execute(
            f"SELECT id, source_type, source_id, text, vector FROM embeddings "
            f"WHERE project_id = ?{type_filter}",
            tuple(params),
        ).fetchall()

        if not rows:
            return []

        query_vec = self._embedding_engine.embed(query)
        vectors = np.array([self._embedding_engine.blob_to_vector(r["vector"]) for r in rows])
        scores = self._embedding_engine.cosine_similarity(query_vec, vectors)

        ranked_indices = np.argsort(scores)[::-1][:top_k]

        results = []
        for idx in ranked_indices:
            row = dict(rows[idx])
            row["score"] = float(scores[idx])
            del row["vector"]
            if row["source_type"] == "memory":
                mem = self.db.execute(
                    "SELECT id, file_path, symbol_name, notes, is_stale FROM memories WHERE id = ?",
                    (row["source_id"],),
                ).fetchone()
                if mem:
                    row.update(dict(mem))
            elif row["source_type"] == "symbol":
                sym = self.db.execute(
                    "SELECT symbol_name, symbol_type, file_path, line_start, line_end, signature "
                    "FROM symbols WHERE id = ?",
                    (row["source_id"],),
                ).fetchone()
                if sym:
                    row.update(dict(sym))
            results.append(row)
        return results

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
