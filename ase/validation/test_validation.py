import unittest
import os
import tempfile
import shutil
from pathlib import Path
from ase.validation.runner import SandboxRunner

class TestSandboxRunner(unittest.TestCase):
    def setUp(self):
        self.src_dir = tempfile.mkdtemp()
        
        # Write dummy project file
        self.py_code = "print('Hello world')"
        self.src_file = Path(self.src_dir) / "main.py"
        with open(self.src_file, "w", encoding="utf-8") as f:
            f.write(self.py_code)
            
        # Create an ignored directory to test filter rules
        self.git_dir = Path(self.src_dir) / ".git"
        self.git_dir.mkdir()
        with open(self.git_dir / "config", "w") as f:
            f.write("mock-git")

    def tearDown(self):
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def test_repository_copying(self):
        runner = SandboxRunner()
        dest_dir = tempfile.mkdtemp()
        
        try:
            runner._copy_repository(self.src_dir, dest_dir)
            
            # Verify main file is copied
            self.assertTrue(os.path.exists(os.path.join(dest_dir, "main.py")))
            
            # Verify git metadata is ignored
            self.assertFalse(os.path.exists(os.path.join(dest_dir, ".git")))
        finally:
            shutil.rmtree(dest_dir, ignore_errors=True)

    def test_run_validation_success(self):
        runner = SandboxRunner()
        res = runner.run_validation(
            repo_path=self.src_dir,
            build_cmd="python3 -c \"print('compiling')\"",
            test_cmd="python3 -c \"print('testing')\""
        )
        
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["build_passed"])
        self.assertTrue(res["tests_passed"])
        self.assertEqual(len(res["errors"]), 0)

    def test_run_validation_build_failure(self):
        runner = SandboxRunner()
        # Trigger explicit compilation error exit code
        res = runner.run_validation(
            repo_path=self.src_dir,
            build_cmd="python3 -c \"import sys; sys.exit(2)\"",
            test_cmd="python3 -c \"print('testing')\""
        )
        
        self.assertEqual(res["status"], "failure")
        self.assertFalse(res["build_passed"])
        # Tests should not run if compile failed
        self.assertTrue(res["tests_passed"])
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("Build Failed (Exit 2)", res["errors"][0])

    def test_run_validation_test_failure(self):
        runner = SandboxRunner()
        # Trigger explicit unit test error exit code
        res = runner.run_validation(
            repo_path=self.src_dir,
            build_cmd="python3 -c \"print('compiling')\"",
            test_cmd="python3 -c \"import sys; sys.exit(3)\""
        )
        
        self.assertEqual(res["status"], "failure")
        self.assertTrue(res["build_passed"])
        self.assertFalse(res["tests_passed"])
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("Tests Failed (Exit 3)", res["errors"][0])

    def test_run_validation_timeout(self):
        runner = SandboxRunner()
        # Force immediate time expired exception on sleep command
        res = runner.run_validation(
            repo_path=self.src_dir,
            build_cmd="python3 -c \"import time; time.sleep(10)\"",
            timeout_secs=1
        )
        
        self.assertEqual(res["status"], "failure")
        self.assertFalse(res["build_passed"])
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("Build timed out", res["errors"][0])

if __name__ == "__main__":
    unittest.main()
