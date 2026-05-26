"""
OCIS Validation Runner — detects test runner and runs tests with timeout.
"""
from __future__ import annotations
import os
import subprocess
from typing import Optional


class ValidationRunner:
    def run_tests(self, repo_path: str, timeout: int = 60) -> dict:
        cmd = self._detect_test_cmd(repo_path)
        if not cmd:
            return {"passed": True, "skipped": True, "reason": "No test runner detected"}
        try:
            r = subprocess.run(cmd, shell=True, cwd=repo_path,
                               capture_output=True, text=True, timeout=timeout)
            return {"passed": r.returncode == 0, "skipped": False,
                    "stdout": r.stdout[-2000:], "stderr": r.stderr[-1000:]}
        except subprocess.TimeoutExpired:
            return {"passed": False, "skipped": False, "reason": f"Timed out after {timeout}s"}
        except Exception as e:
            return {"passed": False, "skipped": False, "reason": str(e)}

    def _detect_test_cmd(self, repo_path: str) -> Optional[str]:
        checks = [
            ("pytest.ini", "python3 -m pytest -x -q --tb=short"),
            ("setup.cfg", "python3 -m pytest -x -q --tb=short"),
            ("pyproject.toml", "python3 -m pytest -x -q --tb=short"),
            ("package.json", "npm test --if-present"),
            ("go.mod", "go test ./... -timeout 60s"),
            ("Cargo.toml", "cargo test --quiet"),
            ("Makefile", "make test"),
        ]
        for fname, cmd in checks:
            if os.path.exists(os.path.join(repo_path, fname)):
                return cmd
        return None
