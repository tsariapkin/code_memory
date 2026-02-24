from __future__ import annotations

import itertools

import networkx as nx


class CodeGraph:
    def __init__(self):
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
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

        id_to_key = {}
        for row in rows:
            row = dict(row)
            key = f"{row['file_path']}::{row['symbol_name']}"
            id_to_key[row["id"]] = key
            self.graph.add_node(
                key,
                symbol_name=row["symbol_name"],
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
            source = id_to_key.get(dep["source_id"])
            target = id_to_key.get(dep["target_id"])
            if source and target:
                self.graph.add_edge(source, target, dep_type=dep["dep_type"])

        self._loaded = True

    def _find_nodes(self, symbol_name: str) -> list[str]:
        """Find all node keys matching a symbol name."""
        return [n for n, d in self.graph.nodes(data=True) if d.get("symbol_name") == symbol_name]

    def get_dependencies(self, symbol_name: str) -> list[dict]:
        """Forward traversal — what does this symbol call/import/inherit?"""
        nodes = self._find_nodes(symbol_name)
        if not nodes:
            return []
        results = []
        for node_key in nodes:
            for _, target, data in self.graph.out_edges(node_key, data=True):
                target_node = self.graph.nodes[target]
                results.append(
                    {
                        "symbol_name": target_node.get("symbol_name", ""),
                        "symbol_type": target_node.get("symbol_type", ""),
                        "file_path": target_node.get("file_path", ""),
                        "signature": target_node.get("signature", ""),
                        "dep_type": data.get("dep_type", ""),
                    }
                )
        return results

    def get_callers(self, symbol_name: str) -> list[dict]:
        """Reverse traversal — who calls/imports this symbol?"""
        nodes = self._find_nodes(symbol_name)
        if not nodes:
            return []
        results = []
        for node_key in nodes:
            for source, _, data in self.graph.in_edges(node_key, data=True):
                source_node = self.graph.nodes[source]
                results.append(
                    {
                        "symbol_name": source_node.get("symbol_name", ""),
                        "symbol_type": source_node.get("symbol_type", ""),
                        "file_path": source_node.get("file_path", ""),
                        "signature": source_node.get("signature", ""),
                        "dep_type": data.get("dep_type", ""),
                    }
                )
        return results

    def trace_call_chain(
        self, from_symbol: str, to_symbol: str, max_depth: int = 5
    ) -> list[list[str]]:
        """Find all simple paths between two symbols up to max_depth."""
        source_nodes = self._find_nodes(from_symbol)
        target_nodes = self._find_nodes(to_symbol)
        if not source_nodes or not target_nodes:
            return []
        all_paths = []
        try:
            for source in source_nodes:
                for target in target_nodes:
                    paths = list(
                        itertools.islice(
                            nx.all_simple_paths(self.graph, source, target, cutoff=max_depth),
                            20,
                        )
                    )
                    # Convert node keys back to symbol names
                    for path in paths:
                        all_paths.append([self.graph.nodes[n].get("symbol_name", n) for n in path])
                    if len(all_paths) >= 20:
                        return all_paths[:20]
        except nx.NetworkXError:
            return []
        return all_paths

    def invalidate(self) -> None:
        """Clear the graph to force rebuild on next query."""
        self.graph.clear()
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded
