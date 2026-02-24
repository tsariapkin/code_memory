from __future__ import annotations

import networkx as nx


class CodeGraph:
    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()
        self._loaded = False

    def build_from_db(self, db, project_id: int) -> None:
        """Load symbols as nodes and dependencies as edges from SQLite."""
        self.graph.clear()

        # Load nodes
        rows = db.execute(
            """SELECT id, symbol_name, symbol_type, file_path,
                      line_start, line_end, signature
               FROM symbols WHERE project_id = ?""",
            (project_id,),
        ).fetchall()

        id_to_name = {}
        for row in rows:
            row = dict(row)
            name = row["symbol_name"]
            id_to_name[row["id"]] = name
            self.graph.add_node(
                name,
                symbol_type=row["symbol_type"],
                file_path=row["file_path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                signature=row["signature"],
            )

        # Load edges
        deps = db.execute(
            """SELECT d.source_id, d.target_id, d.dep_type
               FROM dependencies d
               JOIN symbols s ON d.source_id = s.id
               WHERE s.project_id = ?""",
            (project_id,),
        ).fetchall()

        for dep in deps:
            dep = dict(dep)
            source = id_to_name.get(dep["source_id"])
            target = id_to_name.get(dep["target_id"])
            if source and target:
                self.graph.add_edge(source, target, dep_type=dep["dep_type"])

        self._loaded = True

    def get_dependencies(self, symbol_name: str) -> list[dict]:
        """Forward traversal — what does this symbol call/import/inherit?"""
        if symbol_name not in self.graph:
            return []
        results = []
        for _, target, data in self.graph.out_edges(symbol_name, data=True):
            node = self.graph.nodes[target]
            results.append(
                {
                    "symbol_name": target,
                    "symbol_type": node.get("symbol_type", ""),
                    "file_path": node.get("file_path", ""),
                    "signature": node.get("signature", ""),
                    "dep_type": data.get("dep_type", ""),
                }
            )
        return results

    def get_callers(self, symbol_name: str) -> list[dict]:
        """Reverse traversal — who calls/imports this symbol?"""
        if symbol_name not in self.graph:
            return []
        results = []
        for source, _, data in self.graph.in_edges(symbol_name, data=True):
            node = self.graph.nodes[source]
            results.append(
                {
                    "symbol_name": source,
                    "symbol_type": node.get("symbol_type", ""),
                    "file_path": node.get("file_path", ""),
                    "signature": node.get("signature", ""),
                    "dep_type": data.get("dep_type", ""),
                }
            )
        return results

    def trace_call_chain(
        self, from_symbol: str, to_symbol: str, max_depth: int = 5
    ) -> list[list[str]]:
        """Find all simple paths between two symbols up to max_depth."""
        if from_symbol not in self.graph or to_symbol not in self.graph:
            return []
        try:
            paths = list(nx.all_simple_paths(self.graph, from_symbol, to_symbol, cutoff=max_depth))
        except nx.NetworkXError:
            return []
        return paths

    def invalidate(self) -> None:
        """Clear the graph to force rebuild on next query."""
        self.graph.clear()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded
