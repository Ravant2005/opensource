"""
PRContributionEngine — Fork-first GitHub PR workflow.

Correct flow for contributing to repos you don't own:
  1. Fork the upstream repo into YOUR account via GitHub API
  2. Add your fork as a remote called 'fork'
  3. Push the feature branch to YOUR fork
  4. Open a PR from  YOUR_USERNAME:branch  →  upstream:main
"""
from __future__ import annotations
import os
import time
import subprocess
from typing import List, Dict, Any, Optional
import requests
from ase.config import (
    GITHUB_TOKEN as _CFG_GITHUB_TOKEN,
    GITHUB_USERNAME as _CFG_GITHUB_USERNAME,
    ASE_DRY_RUN as _CFG_DRY_RUN,
)


class PRContributionEngine:
    def __init__(
        self,
        github_token: Optional[str] = None,
        github_username: Optional[str] = None,
    ):
        self.github_token = (
            github_token or _CFG_GITHUB_TOKEN or os.environ.get("GITHUB_TOKEN", "")
        )
        self.github_username = (
            github_username
            or _CFG_GITHUB_USERNAME
            or os.environ.get("GITHUB_USERNAME", "")
        )
        self._session = requests.Session()
        if self.github_token:
            self._session.headers.update(
                {
                    "Authorization": f"token {self.github_token}",
                    "Accept": "application/vnd.github.v3+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _git(self, repo_path: str, args: List[str], check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git"] + args,
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=check,
        )

    def _current_branch(self, repo_path: str) -> str:
        r = self._git(repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        return r.stdout.strip() if r.returncode == 0 else "main"

    def _fork_repo(self, upstream_slug: str) -> Dict[str, Any]:
        """
        Create a fork of upstream_slug (owner/repo) under the authenticated user.
        Returns the fork's full_name and clone_url.
        GitHub forks are async — we poll until ready (max 30 s).
        """
        url = f"https://api.github.com/repos/{upstream_slug}/forks"
        resp = self._session.post(url, json={"default_branch_only": False})
        if resp.status_code not in (202, 200):
            return {"error": f"Fork API returned {resp.status_code}: {resp.text}"}

        fork_data = resp.json()
        fork_slug = fork_data.get("full_name", f"{self.github_username}/{upstream_slug.split('/')[-1]}")
        clone_url = fork_data.get("clone_url", f"https://github.com/{fork_slug}.git")

        # Poll until fork is ready
        for _ in range(12):
            time.sleep(5)
            check = self._session.get(f"https://api.github.com/repos/{fork_slug}")
            if check.status_code == 200:
                data = check.json()
                if not data.get("fork") is False:
                    clone_url = data.get("clone_url", clone_url)
                    break

        return {"full_name": fork_slug, "clone_url": clone_url}

    def _ensure_fork_remote(self, repo_path: str, fork_clone_url: str) -> bool:
        """Add 'fork' remote pointing to the user's fork. Remove stale one if needed."""
        # Inject token into URL for authenticated push
        if self.github_token and "github.com" in fork_clone_url:
            auth_url = fork_clone_url.replace(
                "https://github.com",
                f"https://{self.github_username}:{self.github_token}@github.com",
            )
        else:
            auth_url = fork_clone_url

        # Remove old 'fork' remote if it exists
        self._git(repo_path, ["remote", "remove", "fork"])
        r = self._git(repo_path, ["remote", "add", "fork", auth_url])
        return r.returncode == 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create_pull_request(
        self,
        repo_path: str,
        repo_slug: str,           # upstream "owner/repo"
        branch_name: str,
        commit_msg: str,
        pr_title: str,
        pr_body: str,
        target_branch: str = "main",
        dry_run: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Full fork → branch → commit → push → PR workflow.
        """
        effective_dry_run = dry_run if dry_run is not None else _CFG_DRY_RUN

        if not os.path.exists(repo_path):
            return {"status": "failure", "error": f"Repo path not found: {repo_path}"}

        if not self.github_username:
            return {"status": "failure", "error": "GITHUB_USERNAME not configured in .env"}

        orig_branch = self._current_branch(repo_path)

        # ---- Stage 1: create/switch branch ---------------------------
        r = self._git(repo_path, ["checkout", "-b", branch_name])
        if r.returncode != 0:
            r = self._git(repo_path, ["checkout", branch_name])
            if r.returncode != 0:
                return {"status": "failure", "error": f"Cannot create/switch branch: {r.stderr}"}

        # ---- Stage 2: stage & commit ---------------------------------
        self._git(repo_path, ["add", "--all"])
        r = self._git(repo_path, ["commit", "-m", commit_msg])
        if r.returncode != 0:
            self._git(repo_path, ["checkout", orig_branch])
            self._git(repo_path, ["branch", "-D", branch_name])
            return {"status": "failure", "error": f"Commit failed (no changes?): {r.stderr}"}

        # ---- Dry run -------------------------------------------------
        if effective_dry_run or not self.github_token or self.github_token in ("", "MOCK_TOKEN"):
            self._git(repo_path, ["checkout", orig_branch])
            self._git(repo_path, ["branch", "-D", branch_name])
            return {
                "status": "dry_run",
                "pr_url": f"https://github.com/{repo_slug}/compare/{target_branch}...{self.github_username}:{branch_name}",
                "branch": branch_name,
                "note": "Dry-run: no network calls made. Set ASE_DRY_RUN=false to submit real PR.",
            }

        # ---- Stage 3: fork the upstream repo -------------------------
        fork_info = self._fork_repo(repo_slug)
        if "error" in fork_info:
            self._git(repo_path, ["checkout", orig_branch])
            self._git(repo_path, ["branch", "-D", branch_name])
            return {"status": "failure", "error": fork_info["error"]}

        fork_slug = fork_info["full_name"]
        fork_clone_url = fork_info["clone_url"]

        # ---- Stage 4: add fork remote & push -------------------------
        if not self._ensure_fork_remote(repo_path, fork_clone_url):
            return {"status": "failure", "error": "Failed to add fork remote"}

        r = self._git(repo_path, ["push", "fork", branch_name, "--force-with-lease"])
        if r.returncode != 0:
            self._git(repo_path, ["checkout", orig_branch])
            self._git(repo_path, ["branch", "-D", branch_name])
            return {"status": "failure", "error": f"Push to fork failed: {r.stderr}"}

        # ---- Stage 5: open PR against upstream -----------------------
        # head MUST be "username:branch" for cross-repo PRs
        head = f"{self.github_username}:{branch_name}"
        url = f"https://api.github.com/repos/{repo_slug}/pulls"
        payload = {
            "title": pr_title,
            "body": pr_body,
            "head": head,
            "base": target_branch,
            "maintainer_can_modify": True,
        }
        resp = self._session.post(url, json=payload)

        self._git(repo_path, ["checkout", orig_branch])

        if resp.status_code == 201:
            return {
                "status": "success",
                "pr_url": resp.json().get("html_url", ""),
                "branch": branch_name,
                "fork": fork_slug,
            }
        else:
            return {
                "status": "failure",
                "error": f"PR API {resp.status_code}: {resp.text}",
                "branch": branch_name,
                "fork": fork_slug,
            }
