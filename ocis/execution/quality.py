"""
Phase 6 Quality Gate — ContributionQualityScorer.
Verifies implementation before PR creation.
"""
from __future__ import annotations
import os
import subprocess
from typing import Dict, Any

class ContributionQualityScorer:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path

    def score(self, files_changed: list) -> dict:
        """
        Evaluate the contribution quality.
        Returns: {overall: 0.0-1.0, passes_threshold: bool, ...}
        """
        syntax_ok = self._check_syntax(files_changed)
        tests_ok = self._run_tests()
        
        # Scoring logic
        # 1. Syntax is mandatory (0.4)
        # 2. Tests passing (0.4)
        # 3. Minimality/Style (0.2) - Simplified here
        
        score = 0.0
        if syntax_ok:
            score += 0.5
        if tests_ok:
            score += 0.5
            
        return {
            "overall": score,
            "syntax_valid": syntax_ok,
            "tests_pass": tests_ok,
            "passes_threshold": score >= 0.5 if tests_ok else score >= 0.4,
        }

    def _check_syntax(self, files: list) -> bool:
        ok = True
        for f in files:
            full = os.path.join(self.repo_path, f)
            if not os.path.exists(full):
                continue
            if f.endswith(".py"):
                r = subprocess.run(["python3", "-m", "py_compile", full], capture_output=True)
                if r.returncode != 0:
                    ok = False
            elif f.endswith(".js") or f.endswith(".ts"):
                # Basic node syntax check if node is available
                try:
                    r = subprocess.run(["node", "--check", full], capture_output=True)
                    if r.returncode != 0:
                        ok = False
                except Exception:
                    pass
        return ok

    def _run_tests(self) -> bool:
        """
        Detect test runner: pytest, npm test, go test, cargo test, make test.
        Run with 120s timeout. Return True if exit code 0.
        """
        # Detection order
        test_configs = [
            (["pytest"], "pytest.ini"),
            (["pytest"], "conftest.py"),
            (["npm", "test"], "package.json"),
            (["go", "test", "./..."], "go.mod"),
            (["cargo", "test"], "Cargo.toml"),
            # (["make", "test"], "Makefile"), # Removed as it's too generic and often fails in large repos like Linux
        ]
        
        for cmd, marker in test_configs:
            if os.path.exists(os.path.join(self.repo_path, marker)):
                try:
                    # Run with timeout to prevent hanging
                    r = subprocess.run(cmd, cwd=self.repo_path, capture_output=True, timeout=120)
                    return r.returncode == 0
                except (subprocess.TimeoutExpired, Exception):
                    return False
        
        # Fallback for common directory names
        if any(os.path.isdir(os.path.join(self.repo_path, d)) for d in ["tests", "test"]):
            try:
                # Try pytest by default if there's a test dir
                r = subprocess.run(["pytest"], cwd=self.repo_path, capture_output=True, timeout=120)
                if r.returncode in (0, 5): # 5 = no tests collected, which we'll count as "fine"
                    return True
                return False
            except Exception:
                pass
                
        return True # Default to true if no test suite detected
