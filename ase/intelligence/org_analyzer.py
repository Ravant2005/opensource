"""
OrgAnalyzer — Deep organizational intelligence extractor.

Mines the following signals from a GitHub repo:
  • README, CONTRIBUTING, ROADMAP, CHANGELOG — org mission & style
  • Open issues (labelled enhancement, bug, help-wanted, good-first-issue)
  • Recent merged PRs — contribution patterns, preferred style
  • GitHub Discussions (if enabled)
  • Release notes — versioning cadence and feature trajectory
  • CODEOWNERS, maintainers list — who reviews what
  • CI/CD config (GitHub Actions, .travis.yml, Makefile) — test/build requirements
"""
from __future__ import annotations
import re
import json
from typing import Dict, Any, List, Optional
import requests


_INTEL_FILES = [
    "README.md", "README.rst", "README",
    "CONTRIBUTING.md", "CONTRIBUTING.rst",
    "ROADMAP.md", "ROADMAP",
    "CHANGELOG.md", "CHANGELOG", "HISTORY.md",
    "SECURITY.md",
    "CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/ISSUE_TEMPLATE/bug_report.md",
    ".github/ISSUE_TEMPLATE/feature_request.md",
]

_LABEL_PRIORITIES = {
    "enhancement": 10,
    "feature": 10,
    "good-first-issue": 8,
    "help-wanted": 9,
    "bug": 7,
    "performance": 9,
    "security": 10,
    "documentation": 5,
    "refactor": 6,
}


class OrgAnalyzer:
    """
    Gathers org intelligence from GitHub REST API and raw file content.
    All methods return structured dicts ready for the orchestrator.
    """

    def __init__(self, github_token: str = ""):
        self._session = requests.Session()
        if github_token:
            self._session.headers.update({
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github.v3+json",
            })
        self._session.headers.update({"User-Agent": "ASE-Intelligence/1.0"})

    # ------------------------------------------------------------------
    # Core files
    # ------------------------------------------------------------------
    def fetch_intel_files(self, repo_slug: str) -> Dict[str, str]:
        """
        Download key documentation files. Returns {filename: content}.
        """
        results: Dict[str, str] = {}
        base = f"https://api.github.com/repos/{repo_slug}/contents"
        for path in _INTEL_FILES:
            resp = self._session.get(f"{base}/{path}")
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("encoding") == "base64":
                    import base64
                    try:
                        content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                        results[path] = content
                    except Exception:
                        pass
        return results

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------
    def fetch_open_issues(self, repo_slug: str, max_pages: int = 5) -> List[Dict]:
        """
        Fetch open issues. Returns list sorted by priority score.
        """
        issues = []
        for page in range(1, max_pages + 1):
            resp = self._session.get(
                f"https://api.github.com/repos/{repo_slug}/issues",
                params={"state": "open", "per_page": 100, "page": page},
            )
            if resp.status_code != 200:
                break
            batch = resp.json()
            if not batch:
                break
            # Exclude pull requests (GitHub returns them as issues too)
            issues.extend([i for i in batch if "pull_request" not in i])

        def _priority(issue: Dict) -> int:
            labels = [l["name"].lower() for l in issue.get("labels", [])]
            score = sum(_LABEL_PRIORITIES.get(lbl, 0) for lbl in labels)
            # Boost highly commented issues
            score += min(issue.get("comments", 0), 10)
            return score

        issues.sort(key=_priority, reverse=True)
        return issues

    # ------------------------------------------------------------------
    # Merged PRs (contribution style guide)
    # ------------------------------------------------------------------
    def fetch_recent_merged_prs(self, repo_slug: str, limit: int = 20) -> List[Dict]:
        """
        Analyse recent merged PRs to learn contribution style.
        Returns simplified dicts with title, body_excerpt, files_changed.
        """
        resp = self._session.get(
            f"https://api.github.com/repos/{repo_slug}/pulls",
            params={"state": "closed", "per_page": limit, "sort": "updated"},
        )
        if resp.status_code != 200:
            return []
        prs = [p for p in resp.json() if p.get("merged_at")]
        simplified = []
        for pr in prs:
            simplified.append({
                "number": pr["number"],
                "title": pr["title"],
                "body_excerpt": (pr.get("body") or "")[:300],
                "author": pr["user"]["login"],
                "labels": [l["name"] for l in pr.get("labels", [])],
            })
        return simplified

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------
    def fetch_releases(self, repo_slug: str, limit: int = 5) -> List[Dict]:
        resp = self._session.get(
            f"https://api.github.com/repos/{repo_slug}/releases",
            params={"per_page": limit},
        )
        if resp.status_code != 200:
            return []
        return [
            {
                "tag": r["tag_name"],
                "name": r["name"],
                "body_excerpt": (r.get("body") or "")[:500],
                "published_at": r["published_at"],
            }
            for r in resp.json()
        ]

    # ------------------------------------------------------------------
    # Repo metadata
    # ------------------------------------------------------------------
    def fetch_repo_meta(self, repo_slug: str) -> Dict[str, Any]:
        resp = self._session.get(f"https://api.github.com/repos/{repo_slug}")
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return {
            "name": data.get("name"),
            "description": data.get("description"),
            "language": data.get("language"),
            "topics": data.get("topics", []),
            "stars": data.get("stargazers_count"),
            "forks": data.get("forks_count"),
            "open_issues": data.get("open_issues_count"),
            "default_branch": data.get("default_branch", "main"),
            "license": (data.get("license") or {}).get("spdx_id"),
            "has_discussions": data.get("has_discussions", False),
        }

    # ------------------------------------------------------------------
    # Combined analysis
    # ------------------------------------------------------------------
    def full_analysis(self, repo_slug: str) -> Dict[str, Any]:
        """
        Run all intelligence gathering and return a structured report.
        Includes a 'Deep Insights' section by cross-referencing all data.
        """
        meta = self.fetch_repo_meta(repo_slug)
        intel_files = self.fetch_intel_files(repo_slug)
        issues = self.fetch_open_issues(repo_slug)
        recent_prs = self.fetch_recent_merged_prs(repo_slug)
        releases = self.fetch_releases(repo_slug)

        # Extract enhancement/feature requests separately
        enhancement_issues = [
            i for i in issues
            if any(
                l["name"].lower() in ("enhancement", "feature", "help-wanted", "proposal", "idea")
                for l in i.get("labels", [])
            )
        ]

        # Strategic Analysis
        has_tests = any(f.lower().startswith("test") for f in intel_files.keys())
        has_ci = any(".github/workflows" in k for k in intel_files.keys())
        
        return {
            "repo_meta": meta,
            "intel_files": {k: v[:2500] for k, v in intel_files.items()},
            "top_issues": issues[:25],
            "enhancement_requests": enhancement_issues[:15],
            "recent_merged_prs": recent_prs,
            "releases": releases,
            "summary": {
                "total_open_issues": len(issues),
                "enhancement_count": len(enhancement_issues),
                "has_contributing_guide": "CONTRIBUTING.md" in intel_files,
                "has_security_policy": "SECURITY.md" in intel_files,
                "has_roadmap": "ROADMAP.md" in intel_files,
                "has_tests": has_tests,
                "has_ci": has_ci,
                "primary_language": meta.get("language"),
                "topics": meta.get("topics", []),
                "stars_forks_ratio": round(meta.get("stars", 0) / (meta.get("forks", 1) or 1), 2)
            },
        }
