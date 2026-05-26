import os
import shutil
import tempfile
import subprocess
from typing import List, Dict, Any, Optional

class SandboxRunner:
    def __init__(self, sandbox_root: Optional[str] = None):
        """
        Initializes the Sandbox Runner.
        If sandbox_root is set, creates temporary directories inside it.
        """
        self.sandbox_root = sandbox_root

    def _copy_repository(self, src_path: str, dest_path: str) -> None:
        """
        Copies the repository contents to the destination folder,
        excluding version control (.git) or heavy virtual environments to optimize copy speed.
        """
        ignored_names = (".git", ".venv", "__pycache__", ".pytest_cache", ".qdrant")

        # Perform high-performance replication
        if os.path.isdir(src_path):
            for item in os.listdir(src_path):
                if item in ignored_names:
                    continue
                s = os.path.join(src_path, item)
                d = os.path.join(dest_path, item)
                if os.path.isdir(s):
                    shutil.copytree(s, d, ignore=shutil.ignore_patterns(*ignored_names), symlinks=True)
                else:
                    shutil.copy2(s, d)

    def run_validation(
        self,
        repo_path: str,
        build_cmd: Optional[str] = None,
        test_cmd: Optional[str] = None,
        timeout_secs: int = 30
    ) -> Dict[str, Any]:
        """
        Executes builds and test suites in a fully staged sandbox copy.
        Returns validation outcomes and standard errors.
        """
        if not os.path.exists(repo_path):
            return {
                "status": "failure",
                "build_passed": False,
                "tests_passed": False,
                "errors": [f"Repository path does not exist: {repo_path}"]
            }

        # 1. Prepare temporary staged execution directory
        staged_dir = tempfile.mkdtemp(dir=self.sandbox_root)
        
        build_passed = True
        tests_passed = True
        errors = []

        try:
            # Replicate codebase into isolated container/sandbox
            self._copy_repository(repo_path, staged_dir)

            # 2. Compile/Build Validation Phase
            if build_cmd:
                try:
                    res_build = subprocess.run(
                        build_cmd,
                        shell=True,
                        cwd=staged_dir,
                        capture_output=True,
                        text=True,
                        timeout=timeout_secs
                    )
                    if res_build.returncode != 0:
                        build_passed = False
                        errors.append(f"Build Failed (Exit {res_build.returncode}):\n{res_build.stderr}")
                except subprocess.TimeoutExpired:
                    build_passed = False
                    errors.append(f"Build timed out after {timeout_secs} seconds.")

            # 3. Unit Test Validation Phase (Only runs if build succeeded)
            if build_passed and test_cmd:
                try:
                    res_test = subprocess.run(
                        test_cmd,
                        shell=True,
                        cwd=staged_dir,
                        capture_output=True,
                        text=True,
                        timeout=timeout_secs
                    )
                    if res_test.returncode != 0:
                        tests_passed = False
                        errors.append(f"Tests Failed (Exit {res_test.returncode}):\n{res_test.stderr}")
                except subprocess.TimeoutExpired:
                    tests_passed = False
                    errors.append(f"Tests timed out after {timeout_secs} seconds.")

        finally:
            # 4. Deep Clean verification staged workspace
            shutil.rmtree(staged_dir, ignore_errors=True)

        status = "success" if (build_passed and tests_passed) else "failure"
        return {
            "status": status,
            "build_passed": build_passed,
            "tests_passed": tests_passed,
            "errors": errors
        }
