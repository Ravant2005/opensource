import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from ase.patch.generator import PatchGenerator

class TestPatchGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Write dummy python file for patch application testing
        self.py_code = (
            "def calculate_sum(a, b):\n"
            "    return a + b\n"
            "\n"
            "def run_cmd(cmd):\n"
            "    return os.system(cmd)\n"
        )
        self.src_file = Path(self.temp_dir) / "app.py"
        with open(self.src_file, "w", encoding="utf-8") as f:
            f.write(self.py_code)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_apply_patch(self):
        patch_str = (
            "--- a/app.py\n"
            "+++ b/app.py\n"
            "@@ -5,1 +5,2 @@\n"
            "-    return os.system(cmd)\n"
            "+    import shlex\n"
            "+    return os.system(shlex.quote(cmd))\n"
        )
        
        success = PatchGenerator.apply_patch(str(self.src_file), patch_str)
        self.assertTrue(success)
        
        # Read file back and verify content replacement
        with open(self.src_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        self.assertNotIn("return os.system(cmd)", content)
        self.assertIn("import shlex", content)
        self.assertIn("os.system(shlex.quote(cmd))", content)
        self.assertIn("def calculate_sum", content)  # First function is untouched

    @patch("ase.patch.generator.genai.GenerativeModel")
    def test_generate_patch(self, mock_model_class):
        # Setup mock model response
        mock_model = MagicMock()
        mock_model_class.return_value = mock_model
        
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "status": "success",
            "patch": "--- a/app.py\n+++ b/app.py\n",
            "explanation": "Added security bounds verification checks"
        })
        mock_model.generate_content.return_value = mock_response

        finding = {
            "tool": "semgrep",
            "rule_id": "python.command-injection",
            "file_path": "app.py",
            "line_number": 5,
            "message": "SQL injection vulnerability",
            "severity": "ERROR",
            "cwe": ["CWE-78"]
        }
        
        generator = PatchGenerator(api_key="mock_key")
        result = generator.generate_patch(
            finding,
            code_context="def run_cmd(cmd):\n    return os.system(cmd)\n",
            reasoning_context="Vulnerable shell command execution."
        )
        
        self.assertEqual(result["status"], "success")
        self.assertIn("Added security", result["explanation"])
        self.assertIn("--- a/app.py", result["patch"])

if __name__ == "__main__":
    unittest.main()
