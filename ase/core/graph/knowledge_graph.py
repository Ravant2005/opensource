"""
Knowledge graph layer — Neo4j with in-memory dict fallback for local dev.
"""
from __future__ import annotations
from typing import List, Dict, Any, Optional
from ase.config import NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD


class KnowledgeGraph:
    def __init__(self):
        self._driver = None
        self._mem: Dict[str, List[str]] = {}  # func_name -> [caller_names]
        self._connect()

    def _connect(self):
        if not NEO4J_PASSWORD:
            return
        try:
            from neo4j import GraphDatabase
            self._driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
        except Exception:
            self._driver = None

    def ingest_call_graph(self, file_map: Dict[str, List[Dict]]):
        """Ingest extracted functions into the graph (in-memory or Neo4j)."""
        for file_path, items in file_map.items():
            for item in items:
                if item["type"] == "function":
                    name = item["name"]
                    snippet = item.get("snippet", "")
                    # Detect call sites via simple regex
                    import re
                    calls = re.findall(r"\b([a-zA-Z_]\w+)\s*\(", snippet)
                    for callee in set(calls):
                        if callee != name:
                            self._mem.setdefault(callee, []).append(name)
        if self._driver:
            self._write_to_neo4j()

    def _write_to_neo4j(self):
        try:
            with self._driver.session() as s:
                for callee, callers in self._mem.items():
                    s.run("MERGE (:Function {name: $n})", n=callee)
                    for caller in callers:
                        s.run(
                            "MERGE (a:Function {name:$a}) MERGE (b:Function {name:$b}) MERGE (a)-[:CALLS]->(b)",
                            a=caller, b=callee,
                        )
        except Exception:
            pass

    def find_all_callers(self, func_name: str, hops: int = 3) -> List[str]:
        if self._driver:
            try:
                with self._driver.session() as s:
                    result = s.run(
                        "MATCH (caller)-[:CALLS*1..3]->(f:Function {name:$n}) RETURN caller.name",
                        n=func_name,
                    )
                    return [r["caller.name"] for r in result]
            except Exception:
                pass
        return self._mem.get(func_name, [])

    def close(self):
        if self._driver:
            self._driver.close()
