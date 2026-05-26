"""
OCIS Contribution Engine — fork repo, sync fork, create PR.
"""
from __future__ import annotations
import time
import httpx
from ocis.config import GITHUB_TOKEN, GITHUB_USERNAME, OCIS_DRY_RUN

_GH = "https://api.github.com"
def _get_headers() -> dict:
    from ocis.config import GITHUB_TOKEN as _tok
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _tok:
        h["Authorization"] = f"Bearer {_tok}"
    return h


class ContributionEngine:
    def fork_repository(self, repo_slug: str) -> dict:
        repo_name = repo_slug.split("/")[-1]
        # Check if already forked
        r = httpx.get(f"{_GH}/repos/{GITHUB_USERNAME}/{repo_name}", headers=_get_headers(), timeout=15)
        if r.status_code == 200:
            d = r.json()
            return {"fork_url": d["clone_url"], "fork_slug": f"{GITHUB_USERNAME}/{repo_name}", "existed": True}

        r = httpx.post(f"{_GH}/repos/{repo_slug}/forks", headers=_get_headers(), json={}, timeout=30)
        if r.status_code not in (200, 202):
            raise RuntimeError(f"GitHub fork request failed (HTTP {r.status_code}): {r.text[:200]}")

        for i in range(12):
            time.sleep(10)
            r2 = httpx.get(f"{_GH}/repos/{GITHUB_USERNAME}/{repo_name}", headers=_get_headers(), timeout=15)
            if r2.status_code == 200:
                d = r2.json()
                return {"fork_url": d["clone_url"], "fork_slug": f"{GITHUB_USERNAME}/{repo_name}", "existed": False}
        raise RuntimeError(f"Fork of {repo_slug} not ready after 120s. Check your GitHub account.")

    def sync_fork(self, fork_slug: str) -> bool:
        r = httpx.post(f"{_GH}/repos/{fork_slug}/merge-upstream",
                       headers=_get_headers(), json={"branch": "main"}, timeout=20)
        return r.status_code in (200, 409)

    def create_pull_request(self, fork_slug: str, upstream_slug: str,
                            branch: str, title: str, body: str,
                            base: str = None) -> dict:
        if not GITHUB_TOKEN:
            return {"status": "failed", "error": "GITHUB_TOKEN not set"}

        # Detect default branch if base not provided
        if not base:
            resp = httpx.get(f"{_GH}/repos/{upstream_slug}", headers=_get_headers())
            if resp.status_code != 200:
                 return {"status": "failed", "error": f"Could not fetch upstream repo info: {resp.status_code}"}
            repo_data = resp.json()
            base = repo_data.get("default_branch", "main")

        # GitHub PR head must be "username:branch"
        head = f"{GITHUB_USERNAME}:{branch}"
        
        payload = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": True
        }

        r = httpx.post(f"{_GH}/repos/{upstream_slug}/pulls", headers=_get_headers(),
                       json=payload, timeout=20)
        
        if r.status_code == 201:
            return {"status": "success", "pr_url": r.json().get("html_url", ""), "branch": branch}
        
        # If 404, it might be that the head branch isn't visible yet or repo slugs are wrong
        error_msg = f"{r.status_code}: {r.text[:200]}"
        return {"status": "failed", "error": error_msg, "branch": branch}
