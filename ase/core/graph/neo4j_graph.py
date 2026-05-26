import os
from typing import List, Dict, Any, Optional
from neo4j import GraphDatabase

class Neo4jKnowledgeGraph:
    def __init__(self, uri: Optional[str] = None, user: Optional[str] = None, password: Optional[str] = None):
        """
        Initializes the Neo4j Knowledge Graph interface.
        If connection parameters are not passed, it reads from environment variables.
        """
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.environ.get("NEO4J_USER", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "password")
        self.driver = None

    def connect(self):
        if not self.driver:
            self.driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
        return self

    def close(self):
        if self.driver:
            self.driver.close()
            self.driver = None

    def setup_schema(self):
        """
        Sets up unique constraints and indices to optimize query performance and guarantee data integrity.
        """
        if not self.driver:
            self.connect()

        queries = [
            "CREATE CONSTRAINT unique_module IF NOT EXISTS FOR (m:Module) REQUIRE m.path IS UNIQUE",
            "CREATE CONSTRAINT unique_function IF NOT EXISTS FOR (f:Function) REQUIRE (f.name, f.file) IS UNIQUE",
            "CREATE CONSTRAINT unique_dependency IF NOT EXISTS FOR (d:Dependency) REQUIRE d.name IS UNIQUE",
            "CREATE CONSTRAINT unique_api_endpoint IF NOT EXISTS FOR (a:APIEndpoint) REQUIRE (a.path, a.method) IS UNIQUE",
            "CREATE CONSTRAINT unique_memory_region IF NOT EXISTS FOR (mr:MemoryRegion) REQUIRE mr.owner IS UNIQUE"
        ]
        
        with self.driver.session() as session:
            for q in queries:
                try:
                    session.run(q)
                except Exception as e:
                    # Ignore warnings/errors if database version behaves differently
                    print(f"Schema Setup Hint: {e}")

    def ingest_file_summary(self, summary: Dict[str, Any]):
        """
        Ingests parsed AST details of a module file into the Neo4j Graph.
        """
        if not self.driver:
            self.connect()

        file_path = summary.get("file_path")
        language = summary.get("language")
        
        with self.driver.session() as session:
            # 1. Create/Update Module Node
            session.run(
                """
                MERGE (m:Module {path: $path})
                SET m.name = $name, m.language = $language
                """,
                path=file_path,
                name=os.path.basename(file_path),
                language=language
            )

            # 2. Ingest Functions & EXPORTS Edges
            for func in summary.get("functions", []):
                name = func.get("name")
                line = func.get("start_line", 1)
                sig = func.get("signature", "")
                complexity = func.get("complexity", 1)
                
                session.run(
                    """
                    MERGE (f:Function {name: $name, file: $file})
                    SET f.line = $line, f.language = $language, f.signature = $signature, f.complexity = $complexity
                    WITH f
                    MATCH (m:Module {path: $file})
                    MERGE (m)-[:EXPORTS]->(f)
                    """,
                    name=name,
                    file=file_path,
                    line=line,
                    language=language,
                    signature=sig,
                    complexity=complexity
                )

            # 3. Ingest Imports
            for imp in summary.get("imports", []):
                raw_import = imp.get("raw", "")
                # Simple heuristic to extract potential module path or dependency name
                imported_name = raw_import.replace("import ", "").replace("from ", "").split()[0].strip(";\"'")
                
                # Check if it looks like a local file or external package
                if "/" in imported_name or "." in imported_name or imported_name.endswith(".h"):
                    # Local Module
                    session.run(
                        """
                        MATCH (m:Module {path: $file_path})
                        MERGE (target:Module {path: $imported_path})
                        ON CREATE SET target.name = $imported_name
                        MERGE (m)-[:IMPORTS]->(target)
                        """,
                        file_path=file_path,
                        imported_path=imported_name,
                        imported_name=os.path.basename(imported_name)
                    )
                else:
                    # External Dependency
                    session.run(
                        """
                        MATCH (m:Module {path: $file_path})
                        MERGE (d:Dependency {name: $dep_name})
                        SET d.ecosystem = $ecosystem
                        MERGE (m)-[:DEPENDS_ON]->(d)
                        """,
                        file_path=file_path,
                        dep_name=imported_name,
                        ecosystem=language
                    )

            # 4. Ingest Calls (CALLS Edges)
            for call in summary.get("call_sites", []):
                called_name = call.get("name")
                # Find which function in this file owns the call site (based on line scope)
                call_line = call.get("start_line", 1)
                
                # We locate the enclosing function
                enclosing_func = None
                for func in summary.get("functions", []):
                    if func.get("start_line", 0) <= call_line <= func.get("end_line", 0):
                        enclosing_func = func.get("name")
                        break

                if enclosing_func:
                    session.run(
                        """
                        MATCH (caller:Function {name: $caller_name, file: $file})
                        MERGE (callee:Function {name: $callee_name, file: $file})  // Assume local if not resolved
                        MERGE (caller)-[:CALLS]->(callee)
                        """,
                        caller_name=enclosing_func,
                        callee_name=called_name,
                        file=file_path
                    )
                else:
                    # Top-level call inside the Module directly
                    session.run(
                        """
                        MATCH (m:Module {path: $file})
                        MERGE (callee:Function {name: $callee_name, file: $file})
                        MERGE (m)-[:CALLS]->(callee)
                        """,
                        callee_name=called_name,
                        file=file_path
                    )

            # 5. Ingest Memory Regions (e.g. allocations/deallocations heuristics)
            for func in summary.get("functions", []):
                func_name = func.get("name").lower()
                if "malloc" in func_name or "alloc" in func_name:
                    session.run(
                        """
                        MATCH (f:Function {name: $func_name, file: $file})
                        MERGE (mr:MemoryRegion {owner: $func_name})
                        SET mr.type = "heap", mr.lifetime = "dynamic"
                        MERGE (f)-[:ALLOCATES]->(mr)
                        """,
                        func_name=func.get("name"),
                        file=file_path
                    )

            # 6. Ingest API Endpoints (e.g. web entry points routing)
            for func in summary.get("functions", []):
                sig = func.get("signature", "").lower()
                if "route(" in sig or "get(" in sig or "post(" in sig:
                    # Guess method and path
                    method = "GET"
                    if "post" in sig:
                        method = "POST"
                    path = f"/api/{func.get('name')}"
                    
                    session.run(
                        """
                        MATCH (f:Function {name: $func_name, file: $file})
                        MERGE (a:APIEndpoint {path: $path, method: $method})
                        SET a.auth_required = false
                        MERGE (a)-[:TRUSTS]->(f)
                        """,
                        func_name=func.get("name"),
                        file=file_path,
                        path=path,
                        method=method
                    )

    # ------------------ CYPHER SECURITY QUERY HELPERS ------------------

    def find_all_callers(self, function_name: str) -> List[Dict[str, Any]]:
        """
        Traces and returns all direct/indirect callers of a function (arbitrary path length).
        """
        if not self.driver:
            self.connect()

        query = """
        MATCH path = (caller:Function)-[:CALLS*]->(target:Function {name: $name})
        RETURN caller.name AS caller_name, caller.file AS caller_file, length(path) AS depth
        ORDER BY depth ASC
        """
        with self.driver.session() as session:
            result = session.run(query, name=function_name)
            return [dict(record) for record in result]

    def trace_data_flow(self, source_name: str, sink_name: str) -> List[Dict[str, Any]]:
        """
        Traces flow paths from a given source (e.g. untrusted input) to a sink (e.g. database, malloc, command execution).
        """
        if not self.driver:
            self.connect()

        query = """
        MATCH path = shortestPath((source:Function {name: $source})-[:CALLS|ALLOCATES*]->(sink:Function {name: $sink}))
        RETURN [node in nodes(path) | {name: node.name, label: labels(node)[0], file: node.file}] AS flow_path
        """
        with self.driver.session() as session:
            result = session.run(query, source=source_name, sink=sink_name)
            return [dict(record) for record in result]

    def find_trust_boundary_crossings(self) -> List[Dict[str, Any]]:
        """
        Identifies potential trust boundary crossings, such as unauthenticated public
        API endpoints invoking privileged internal functions.
        """
        if not self.driver:
            self.connect()

        query = """
        MATCH (api:APIEndpoint)-[:TRUSTS]->(entry:Function)
        MATCH path = (entry)-[:CALLS*]->(privileged:Function)
        WHERE privileged.name IN ['system', 'exec', 'malloc', 'db_write', 'admin_override']
        RETURN api.path AS api_path, api.method AS api_method, 
               privileged.name AS privileged_sink, [node in nodes(path) | node.name] AS execution_chain
        """
        with self.driver.session() as session:
            result = session.run(query)
            return [dict(record) for record in result]
