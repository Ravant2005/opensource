import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from ase.contribution.engine import PRContributionEngine

class TestPRContributionEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Initialize a mock source file
        self.src_file = Path(self.temp_dir) / "app.py"
        with open(self.src_file, "w", encoding="utf-8") as f:
            f.write("print('Hello')")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("ase.contribution.engine.PRContributionEngine._run_git")
    def test_dry_run_simulation(self, mock_run_git):
        # Configure mock local git returns
        mock_run_git.return_value = True
        
        engine = PRContributionEngine(github_token="MOCK_TOKEN")
        res = engine.create_pull_request(
            repo_path=self.temp_dir,
            repo_slug="google/ase",
            branch_name="security-fix-cwe-78",
            commit_msg="Mitigate command injections",
            pr_title="Security Patch: Fix CWE-78 vulnerable shell cmd",
            pr_body="Thoroughly sanitizes parameter vectors before command runs.",
            dry_run=True
        )
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["branch"], "security-fix-cwe-78")
        self.assertEqual(res["pr_url"], "https://github.com/google/ase/pull/42")
        self.assertIn("Simulated Contribution", res["note"])

    @patch("ase.contribution.engine.subprocess.run")
    def test_local_git_flow(self, mock_run):
        # Setup Git subprocess executions to succeed
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res
        
        engine = PRContributionEngine()
        success = engine._run_git(self.temp_dir, ["checkout", "-b", "test-branch"])
        
        self.assertTrue(success)
        mock_run.assert_called_once_with(
            ["git", "checkout", "-b", "test-branch"],
            cwd=self.temp_dir, capture_output=True, text=True, check=False
        )

    @patch("ase.contribution.engine.PRContributionEngine._run_git")
    @patch("ase.contribution.engine.requests.post")
    def test_github_api_pr_creation(self, mock_post, mock_run_git):
        # Configure mock remote git push success
        mock_run_git.return_value = True
        
        # Configure mock GitHub REST pull request successful return
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.json.return_value = {
            "html_url": "https://github.com/google/ase/pull/99"
        }
        mock_post.return_value = mock_response

        engine = PRContributionEngine(github_token="ACTIVE_TOKEN")
        res = engine.create_pull_request(
            repo_path=self.temp_dir,
            repo_slug="google/ase",
            branch_name="patch-cwe-89",
            commit_msg="Fix sql injection",
            pr_title="Fix vulnerability",
            pr_body="Parameterized queries implemented.",
            target_branch="develop"
        )
        
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["pr_url"], "https://github.com/google/ase/pull/99")
        
        # Verify JSON REST parameters are mapped exactly
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.github.com/repos/google/ase/pulls")
        self.assertEqual(kwargs["json"]["head"], "patch-cwe-89")
        self.assertEqual(kwargs["json"]["base"], "develop")
        self.assertEqual(kwargs["headers"]["Authorization"], "token ACTIVE_TOKEN")

if __name__ == "__main__":
    unittest.main()
