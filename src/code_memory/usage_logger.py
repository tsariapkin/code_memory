from __future__ import annotations

import time

from src.code_memory.db import Database

_MAX_ARGS_LENGTH = 200


def log_tool_usage(
    db: Database,
    project_id: int,
    tool_name: str,
    args_summary: str,
    result_empty: bool,
) -> None:
    truncated = args_summary[:_MAX_ARGS_LENGTH] if args_summary else ""
    db.execute(
        """INSERT INTO tool_usage (tool_name, project_id, timestamp, args_summary, result_empty)
           VALUES (?, ?, ?, ?, ?)""",
        (tool_name, project_id, time.time(), truncated, result_empty),
    )
    db.conn.commit()


def get_usage_stats(db: Database, project_id: int, days: int = 7) -> dict:
    cutoff = time.time() - (days * 86400)
    rows = db.execute(
        """SELECT tool_name,
                  COUNT(*) as total,
                  SUM(CASE WHEN result_empty THEN 1 ELSE 0 END) as empty
           FROM tool_usage
           WHERE project_id = ? AND timestamp >= ?
           GROUP BY tool_name
           ORDER BY total DESC""",
        (project_id, cutoff),
    ).fetchall()

    return {row["tool_name"]: {"total": row["total"], "empty": row["empty"]} for row in rows}
