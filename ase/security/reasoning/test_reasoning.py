import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from ase.security.reasoning.agent import ReasoningAgent

class TestReasoningAgent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Write mock source file for context extraction
        self.py_code = "\n".join([f"line_{i}" for i in range(1, 30)])
        self.src_file = Path(self.temp_dir) / "app.py"
        with open(self.src_file, "w", encoding="utf-8") as f:
            f.write(self.py_code)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_ast_snippet(self):
        agent = ReasoningAgent()
        snippet = agent.extract_ast_snippet(self.temp_dir, "app.py", 15, context_window=5)
        
        # Verify lines surrounding line 15 are grabbed
        self.assertIn("15 | line_15", snippet)
        self.assertIn("10 | line_10", snippet)
        self.assertIn("20 | line_20", snippet)
        self.assertNotIn("8 | line_8", snippet)
        self.assertNotIn("22 | line_22", snippet)
        self.assertIn("--> ", snippet)  # line marker

    def test_compile_context(self):
        finding = {
            "tool": "semgrep",
            "rule_id": "python.vuln",
            "file_path": "app.py",
            "line_number": 15,
            "message": "Dangerous command",
            "severity": "WARNING",
            "cwe": ["CWE-78"]
        }
        
        # Mock Graph Layer
        mock_graph = MagicMock()
        mock_graph.find_all_callers.return_value = [
            {"caller_name": "main", "caller_file": "main.py", "depth": 1}
        ]
        
        # Mock RAG Layer
        mock_rag = MagicMock()
        mock_rag.find_historical_fixes.return_value = [
            {"text": "sanitized = clean(val)", "metadata": {"name": "clean"}, "score": 0.8}
        ]
        
        agent = ReasoningAgent()
        context = agent.compile_context(finding, self.temp_dir, mock_graph, mock_rag)
        
        self.assertIn("15 | line_15", context["ast"])
        self.assertEqual(len(context["graph_callers"]), 1)
        self.assertEqual(context["graph_callers"][0]["caller_name"], "main")
        self.assertEqual(len(context["rag_fixes"]), 1)
        self.assertEqual(context["rag_fixes"][0]["metadata"]["name"], "clean")

    @patch("ase.security.reasoning.agent.genai.GenerativeModel")
    def test_analyze_finding(self, mock_model_class):
        # Setup mock model response
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "is_false_positive": True,
            "confidence_score": 0.95,
            "exploit_scenario": "N/A",
            "reasoning": "The parameter is thoroughly sanitized before execution."
        })
        mock_model.generate_content.return_value = mock_response

        finding = {
            "tool": "semgrep",
            "rule_id": "python.vuln",
            "file_path": "app.py",
            "line_number": 15,
            "message": "Dangerous command",
            "severity": "WARNING",
            "cwe": ["CWE-78"]
        }
        
        agent = ReasoningAgent(api_key="mock_key")
        result = agent.analyze_finding(finding, self.temp_dir)
        
        self.assertTrue(result["is_false_positive"])
        self.assertEqual(result["confidence_score"], 0.95)
        self.assertEqual(result["exploit_scenario"], "N/A")
        self.assertIn("sanitized", result["reasoning"])

if __name__ == "__main__":
    unittest.main()
