import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from ase.security.static.analyzer import (
    SemgrepAnalyzer, CodeQLAnalyzer, GitleaksAnalyzer,
    TrivyAnalyzer, StaticAnalysisOrchestrator, UnifiedFinding
)

class TestUnifiedFinding(unittest.TestCase):
    def test_exploitability_score_high_severity_with_cwe(self):
        f = UnifiedFinding("semgrep", "r", "f.py", 1, "msg", "ERROR", ["CWE-78"])
        self.assertGreater(f.exploitability_score, 0.85)

    def test_exploitability_score_info(self):
        f = UnifiedFinding("semgrep", "r", "f.py", 1, "msg", "INFO", [])
        self.assertLessEqual(f.exploitability_score, 0.2)

    def test_dedup_key_stability(self):
        f1 = UnifiedFinding("semgrep", "rules.x", "app.py", 10, "m", "ERROR", [])
        f2 = UnifiedFinding("semgrep", "rules.x", "app.py", 10, "different", "WARNING", [])
        self.assertEqual(f1.dedup_key, f2.dedup_key)

    def test_to_dict_contains_all_fields(self):
        f = UnifiedFinding("trivy", "CVE-2023-1", "go.sum", 1, "msg", "HIGH", ["CWE-119"], cve="CVE-2023-1")
        d = f.to_dict()
        for key in ("tool", "rule_id", "file_path", "line_number", "message",
                    "severity", "cwe", "cve", "snippet", "exploitability_score", "dedup_key"):
            self.assertIn(key, d)


class TestSemgrepAnalyzer(unittest.TestCase):
    def test_parse_json(self):
        output = {"results": [{"check_id": "rules.python.injection", "path": "app/vuln.py",
            "start": {"line": 15}, "extra": {"message": "SQL injection", "severity": "ERROR",
            "metadata": {"cwe": ["CWE-89: SQL injection"]}}}]}
        findings = SemgrepAnalyzer().parse_json(json.dumps(output))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].cwe, ["CWE-89"])
        self.assertEqual(findings[0].severity, "ERROR")

    @patch("ase.security.static.analyzer.subprocess.run")
    def test_scan_cli(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({"results": []}))
        findings = SemgrepAnalyzer("mock-semgrep").scan("/fake/repo")
        self.assertEqual(findings, [])


class TestCodeQLAnalyzer(unittest.TestCase):
    def test_parse_sarif(self):
        sarif = {"runs": [{"tool": {"driver": {"rules": [{"id": "cpp/xss",
            "properties": {"tags": ["external/cwe/cwe-079"]},
            "defaultConfiguration": {"level": "error"}}]}},
            "results": [{"ruleId": "cpp/xss", "message": {"text": "XSS"},
            "locations": [{"physicalLocation": {"artifactLocation": {"uri": "src/s.cpp"},
            "region": {"startLine": 45}}}]}]}]}
        tmp = tempfile.NamedTemporaryFile(suffix=".sarif", delete=False, mode="w")
        json.dump(sarif, tmp); tmp.close()
        findings = CodeQLAnalyzer().parse_sarif(tmp.name)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].cwe, ["CWE-79"])
        self.assertEqual(findings[0].severity, "ERROR")
        import os; os.unlink(tmp.name)


class TestGitleaksAnalyzer(unittest.TestCase):
    def test_parse_json(self):
        leaks = [{"RuleID": "aws-access-token", "File": "config.py",
                  "StartLine": 5, "Description": "AWS key", "Secret": "AKIAIOSFODNN7EXAMPLE"}]
        findings = GitleaksAnalyzer().parse_json(json.dumps(leaks))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].tool, "gitleaks")
        self.assertEqual(findings[0].cwe, ["CWE-312"])
        self.assertIn("...", findings[0].snippet)


class TestTrivyAnalyzer(unittest.TestCase):
    def test_parse_json(self):
        data = {"Results": [{"Target": "go.sum", "Vulnerabilities": [
            {"VulnerabilityID": "CVE-2023-44487", "PkgName": "golang.org/x/net",
             "InstalledVersion": "0.10.0", "FixedVersion": "0.17.0",
             "Severity": "HIGH", "Description": "HTTP/2 DDOS", "CweIDs": ["400"]}
        ]}]}
        findings = TrivyAnalyzer().parse_json(json.dumps(data))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].cve, "CVE-2023-44487")
        self.assertEqual(findings[0].cwe, ["CWE-400"])


class TestStaticAnalysisOrchestrator(unittest.TestCase):
    @patch("ase.security.static.analyzer.TrivyAnalyzer.scan")
    @patch("ase.security.static.analyzer.GitleaksAnalyzer.scan")
    @patch("ase.security.static.analyzer.SemgrepAnalyzer.scan")
    def test_deduplication_and_ranking(self, mock_semgrep, mock_gitleaks, mock_trivy):
        # Produce two findings with the same dedup key from different tools
        f1 = UnifiedFinding("semgrep", "rules.x", "app.py", 10, "m", "ERROR", ["CWE-78"])
        f2 = UnifiedFinding("semgrep", "rules.x", "app.py", 10, "m", "ERROR", ["CWE-78"])
        f3 = UnifiedFinding("gitleaks", "aws-key", "cfg.py", 1, "s", "ERROR", ["CWE-312"])
        mock_semgrep.return_value = [f1, f2]
        mock_gitleaks.return_value = [f3]
        mock_trivy.return_value = []
        results = StaticAnalysisOrchestrator().run("/fake/repo")
        # f1 and f2 share dedup key — only 1 should survive
        keys = [r.dedup_key for r in results]
        self.assertEqual(len(keys), len(set(keys)))
        # Sorted by exploitability descending
        scores = [r.exploitability_score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
