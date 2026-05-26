import unittest
from unittest.mock import MagicMock, patch
from ase.core.graph.neo4j_graph import Neo4jKnowledgeGraph

class TestNeo4jKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        # We patch standard GraphDatabase driver creation to avoid connecting to actual server
        self.patcher = patch("ase.core.graph.neo4j_graph.GraphDatabase.driver")
        self.mock_driver_creator = self.patcher.start()
        self.mock_driver = MagicMock()
        self.mock_driver_creator.return_value = self.mock_driver
        
        self.mock_session = MagicMock()
        self.mock_driver.session.return_value = self.mock_session

        self.graph = Neo4jKnowledgeGraph(
            uri="bolt://localhost:7687",
            user="neo4j",
            password="testpassword"
        )
        self.graph.connect()

    def tearDown(self):
        self.patcher.stop()

    def test_connect(self):
        self.mock_driver_creator.assert_called_once_with(
            "bolt://localhost:7687",
            auth=("neo4j", "testpassword")
        )

    def test_setup_schema(self):
        self.graph.setup_schema()
        # Verify schema setups run correctly inside a session context manager
        self.mock_driver.session.assert_called()
        self.mock_session.__enter__.return_value.run.assert_called()

    def test_ingest_file_summary(self):
        summary = {
            "file_path": "ase/core/parsers/ingestion.py",
            "language": "python",
            "functions": [
                {
                    "name": "ingest",
                    "signature": "def ingest(...)",
                    "start_line": 20,
                    "end_line": 35,
                    "complexity": 1
                }
            ],
            "classes": [
                {
                    "name": "RepoIngestionPipeline",
                    "start_line": 10,
                    "end_line": 40,
                    "bases": []
                }
            ],
            "imports": [
                {
                    "raw": "import git",
                    "start_line": 3
                }
            ],
            "call_sites": [
                {
                    "name": "process_directory",
                    "start_line": 25
                }
            ],
            "globals": []
        }
        
        self.graph.ingest_file_summary(summary)
        
        # Verify session runs multiple statements (Module, Functions, Imports, Calls, etc.)
        self.mock_session.__enter__.return_value.run.assert_called()
        calls = self.mock_session.__enter__.return_value.run.call_args_list
        
        # Ensure MERGE for Module was triggered
        module_merge_called = any("Module" in c[0][0] for c in calls)
        self.assertTrue(module_merge_called, "Expected Module MERGE query to be executed.")
        
        # Ensure MERGE for Function was triggered
        function_merge_called = any("Function" in c[0][0] for c in calls)
        self.assertTrue(function_merge_called, "Expected Function MERGE query to be executed.")

    def test_find_all_callers(self):
        # Setup mock record return
        mock_run = self.mock_session.__enter__.return_value.run
        mock_result = MagicMock()
        mock_result.__iter__.return_value = [
            {"caller_name": "caller_a", "caller_file": "file_a.py", "depth": 1},
            {"caller_name": "caller_b", "caller_file": "file_b.py", "depth": 2}
        ]
        mock_run.return_value = mock_result

        callers = self.graph.find_all_callers("target_function")
        
        self.assertEqual(len(callers), 2)
        self.assertEqual(callers[0]["caller_name"], "caller_a")
        self.assertEqual(callers[1]["depth"], 2)

    def test_trace_data_flow(self):
        mock_run = self.mock_session.__enter__.return_value.run
        mock_result = MagicMock()
        mock_result.__iter__.return_value = [
            {"flow_path": [{"name": "source", "label": "Function", "file": "src.py"}, 
                           {"name": "sink", "label": "Function", "file": "sink.py"}]}
        ]
        mock_run.return_value = mock_result

        flow = self.graph.trace_data_flow("source", "sink")
        
        self.assertEqual(len(flow), 1)
        self.assertEqual(len(flow[0]["flow_path"]), 2)
        self.assertEqual(flow[0]["flow_path"][0]["name"], "source")

    def test_find_trust_boundary_crossings(self):
        mock_run = self.mock_session.__enter__.return_value.run
        mock_result = MagicMock()
        mock_result.__iter__.return_value = [
            {
                "api_path": "/api/upload",
                "api_method": "POST",
                "privileged_sink": "system",
                "execution_chain": ["upload", "process", "system"]
            }
        ]
        mock_run.return_value = mock_result

        crossings = self.graph.find_trust_boundary_crossings()
        
        self.assertEqual(len(crossings), 1)
        self.assertEqual(crossings[0]["api_path"], "/api/upload")
        self.assertEqual(crossings[0]["privileged_sink"], "system")

if __name__ == "__main__":
    unittest.main()
