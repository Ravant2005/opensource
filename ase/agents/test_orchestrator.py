import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from ase.agents.orchestrator import AgentOrchestrator, JobStatus

class TestAgentOrchestrator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        # Write a small python file so the sandbox has something to copy
        (Path(self.temp_dir) / "app.py").write_text("print('hello')")
        self.orch = AgentOrchestrator(dry_run=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_submit_creates_job(self):
        job_id = self.orch.submit("https://github.com/test/repo", self.temp_dir, "test/repo")
        self.assertIn(job_id, self.orch._jobs)
        job = self.orch.get_job(job_id)
        self.assertEqual(job.status, JobStatus.SUBMITTED)

    def test_list_jobs(self):
        self.orch.submit("https://github.com/a/b", self.temp_dir, "a/b")
        self.orch.submit("https://github.com/c/d", self.temp_dir, "c/d")
        jobs = self.orch.list_jobs()
        self.assertEqual(len(jobs), 2)

    def test_get_job_missing(self):
        self.assertIsNone(self.orch.get_job("nonexistent"))

    @patch("ase.security.static.analyzer.StaticAnalysisOrchestrator")
    def test_run_phase_analyze_calls_orchestrator(self, mock_cls):
        mock_instance = MagicMock()
        mock_instance.run.return_value = []
        mock_cls.return_value = mock_instance

        job_id = self.orch.submit("url", self.temp_dir, "r/r")
        # Patch at the import level inside the method's module
        import ase.security.static.analyzer as mod
        original = mod.StaticAnalysisOrchestrator
        mod.StaticAnalysisOrchestrator = mock_cls
        result = self.orch.run_phase_analyze(job_id)
        mod.StaticAnalysisOrchestrator = original
        self.assertTrue(result)

    def test_full_pipeline_completes(self):
        """Full pipeline with all external calls mocked should complete without error."""
        with patch("ase.security.static.analyzer.SemgrepAnalyzer.scan", return_value=[]), \
             patch("ase.security.static.analyzer.GitleaksAnalyzer.scan", return_value=[]), \
             patch("ase.security.static.analyzer.TrivyAnalyzer.scan", return_value=[]), \
             patch("ase.security.reasoning.agent.genai.GenerativeModel") as mock_model, \
             patch("ase.patch.generator.genai.GenerativeModel") as mock_pmodel, \
             patch("ase.contribution.engine.PRContributionEngine._run_git", return_value=True):

            mock_resp = MagicMock()
            mock_resp.text = '{"is_false_positive": true, "confidence_score": 0.9, "exploit_scenario": "N/A", "reasoning": "no issue"}'
            mock_model.return_value.generate_content.return_value = mock_resp

            mock_presp = MagicMock()
            mock_presp.text = '{"status": "success", "patch": "", "explanation": "fixed"}'
            mock_pmodel.return_value.generate_content.return_value = mock_presp

            job_id = self.orch.submit("url", self.temp_dir, "test/repo")
            job = self.orch.run_full_pipeline(job_id)
            # Pipeline should finish (findings=[] so patches/PRs will be empty, status=DONE)
            self.assertIn(job.status, (JobStatus.DONE, JobStatus.CONTRIBUTING))

if __name__ == "__main__":
    unittest.main()
