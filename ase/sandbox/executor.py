"""
SandboxExecutor — Isolated workspace for code changes.

Strategy:
  1. Clone the target repo into a fresh temp directory (sandbox)
  2. All patch applications and code modifications happen in the sandbox
  3. Original cloned repo is NEVER touched
  4. After validation passes, sandbox is used as the source for the PR
  5. Sandbox is cleaned up after the job completes
"""
from __future__ import annotations
import os
import shutil
import tempfile
import subprocess
from typing import Optional, Dict, Any


class SandboxExecutor:
    """
    Manages an isolated copy of a repository for safe experimentation.
    """

    def __init__(self):
        self._sandboxes: Dict[str, str] = {}  # job_id -> sandbox_path

    def create_sandbox(self, source_repo_path: str, job_id: str) -> str:
        """
        Copy the repo into a fresh temp directory.
        Returns the sandbox path.
        """
        sandbox_dir = tempfile.mkdtemp(prefix=f"ase_sandbox_{job_id}_")
        shutil.copytree(source_repo_path, sandbox_dir, dirs_exist_ok=True)
        self._sandboxes[job_id] = sandbox_dir
        return sandbox_dir

    def get_sandbox(self, job_id: str) -> Optional[str]:
        return self._sandboxes.get(job_id)

    def run_in_sandbox(
        self,
        job_id: str,
        cmd: str,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """
        Run a shell command inside the sandbox. Returns {returncode, stdout, stderr}.
        """
        sandbox = self._sandboxes.get(job_id)
        if not sandbox or not os.path.exists(sandbox):
            return {"returncode": -1, "stdout": "", "stderr": "Sandbox not found"}
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=sandbox,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout[:4000],
                "stderr": result.stderr[:2000],
            }
        except subprocess.TimeoutExpired:
            return {"returncode": -1, "stdout": "", "stderr": f"Command timed out after {timeout}s"}
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def destroy_sandbox(self, job_id: str) -> bool:
        """Remove the sandbox directory."""
        sandbox = self._sandboxes.pop(job_id, None)
        if sandbox and os.path.exists(sandbox):
            shutil.rmtree(sandbox, ignore_errors=True)
            return True
        return False

    def apply_patch_in_sandbox(
        self, job_id: str, target_relative_path: str, patch_str: str
    ) -> bool:
        """
        Apply a unified diff patch to a file inside the sandbox.
        """
        sandbox = self._sandboxes.get(job_id)
        if not sandbox:
            return False
        from ase.patch.generator import PatchGenerator
        full_path = os.path.join(sandbox, target_relative_path)
        return PatchGenerator.apply_patch(full_path, patch_str)
