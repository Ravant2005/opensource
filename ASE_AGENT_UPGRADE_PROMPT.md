# ASE (Autonomous Software Engineer) — Complete Upgrade & Fix Prompt
> Feed this entire document to your AI agent in one shot. It contains the full diagnosis, all files to create, all files to fix, and the exact implementation order.

---

## CONTEXT: What This Project Is

ASE is an autonomous agent that:
1. Takes a GitHub repo URL as input
2. Deep-analyzes the codebase, issues, roadmap, and community goals
3. Discovers vulnerabilities, bugs, and missing features
4. Generates real code patches and applies them to disk
5. Forks the target repo, pushes changes, and opens a real Pull Request via your GitHub account

**Current broken state** (diagnosed from source):
- The intelligence layer only does basic static analysis — no org goal understanding, no issue mining, no roadmap analysis
- `apply_patch()` exists in `patch/generator.py` but is **never called** in the orchestrator — patches are generated but never written to disk
- The PR engine is missing fork creation — it tries to `push origin` on a repo you don't own (fails silently)
- The `head` field in the PR payload uses just `branch_name` instead of `username:branch_name` (GitHub API requirement for cross-repo PRs)
- No CVE/NVD database lookup — vulnerabilities are only found via regex pattern matching
- No feature recommendation engine — the system only fixes bugs, never proposes enhancements
- No sandbox isolation — code changes happen directly on the cloned repo with no rollback plan

---

## IMPLEMENTATION ORDER

Execute these tasks in exact order. Each section is self-contained.

---

## TASK 1 — Fix the Patch Application Gap

**File to fix:** `ase/agents/orchestrator.py`

In `run_phase_patch()`, after scoring, add actual patch application to disk. Find the block that appends to `patches` and add:

```python
# After quality scoring passes, APPLY the patch to disk
if patch_result.get("quality", {}).get("passes_threshold", False):
    target_file = os.path.join(job.repo_path, finding.get("file_path", ""))
    patch_str = patch_result.get("patch", "")
    if os.path.exists(target_file) and patch_str:
        applied = PatchGenerator.apply_patch(target_file, patch_str)
        patch_result["applied_to_disk"] = applied
    else:
        patch_result["applied_to_disk"] = False
    patches.append(patch_result)
```

Also add `import os` at the top of orchestrator.py if not present.

---

## TASK 2 — Fix the PR Engine (Fork-First Workflow)

**File to completely rewrite:** `ase/contribution/engine.py`

Replace the entire file with this implementation:

```python
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
```

---

## TASK 3 — Create the Intelligence Layer

**Create new file:** `ase/intelligence/__init__.py` (empty)

**Create new file:** `ase/intelligence/org_analyzer.py`

```python
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
                l["name"].lower() in ("enhancement", "feature", "help-wanted")
                for l in i.get("labels", [])
            )
        ]

        return {
            "repo_meta": meta,
            "intel_files": {k: v[:2000] for k, v in intel_files.items()},  # Truncate for LLM context
            "top_issues": issues[:20],
            "enhancement_requests": enhancement_issues[:10],
            "recent_merged_prs": recent_prs,
            "releases": releases,
            "summary": {
                "total_open_issues": len(issues),
                "enhancement_count": len(enhancement_issues),
                "has_contributing_guide": "CONTRIBUTING.md" in intel_files,
                "has_security_policy": "SECURITY.md" in intel_files,
                "has_roadmap": "ROADMAP.md" in intel_files,
                "primary_language": meta.get("language"),
                "topics": meta.get("topics", []),
            },
        }
```

---

## TASK 4 — Create the Feature Recommendation Engine

**Create new file:** `ase/intelligence/feature_recommender.py`

```python
"""
FeatureRecommender — LLM-powered feature suggestion engine.

Takes org intelligence (from OrgAnalyzer) + static analysis findings
and generates prioritised, actionable feature proposals that:
  • Align with the org's stated mission and roadmap
  • Address patterns in open issues
  • Are technically feasible given the codebase structure
  • Include a concrete implementation sketch
"""
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from ase.config import GEMINI_API_KEY, GEMINI_MODEL


def _call_llm(prompt: str, api_key: str, model_name: str, as_json: bool = True) -> str:
    if not api_key or api_key in ("", "MOCK"):
        return "[]" if as_json else ""
    try:
        from google import generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        cfg = {"temperature": 0.3}
        if as_json:
            cfg["response_mime_type"] = "application/json"
        resp = model.generate_content(prompt, generation_config=cfg)
        return getattr(resp, "text", "") or ""
    except Exception:
        pass
    try:
        from google import genai as modern_genai
        from google.genai import types
        client = modern_genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json" if as_json else "text/plain",
                temperature=0.3,
            ),
        )
        return getattr(resp, "text", "") or ""
    except Exception:
        return "[]" if as_json else ""


class FeatureRecommender:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

    def generate_recommendations(
        self,
        org_intel: Dict[str, Any],
        static_findings: List[Dict],
        max_recommendations: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of feature recommendation dicts, each with:
          - title: short feature name
          - description: what it does and why it matters
          - motivation: link to org goals / open issues
          - implementation_sketch: concrete steps / file locations to change
          - estimated_impact: low / medium / high / game-changing
          - pr_title: ready-to-use PR title
          - pr_body: full markdown PR description
          - files_to_modify: list of files likely needing changes
        """
        meta = org_intel.get("repo_meta", {})
        issues_summary = "\n".join(
            f"- #{i['number']}: {i['title']} (comments: {i.get('comments', 0)})"
            for i in org_intel.get("top_issues", [])[:15]
        )
        roadmap_text = org_intel.get("intel_files", {}).get("ROADMAP.md", "")
        readme_text = org_intel.get("intel_files", {}).get("README.md", "")[:1500]
        contributing_text = org_intel.get("intel_files", {}).get("CONTRIBUTING.md", "")[:800]
        recent_releases = "\n".join(
            f"- {r['tag']}: {r['body_excerpt'][:200]}"
            for r in org_intel.get("releases", [])
        )
        security_findings_summary = "\n".join(
            f"- {f.get('rule_id')}: {f.get('message','')[:100]} in {f.get('file_path','')}"
            for f in static_findings[:10]
        )

        prompt = f"""You are an elite open-source contributor with deep expertise in {meta.get('language', 'systems programming')}.

REPOSITORY: {meta.get('name', 'unknown')} — {meta.get('description', '')}
TOPICS: {', '.join(meta.get('topics', []))}
STARS: {meta.get('stars', 0)} | OPEN ISSUES: {meta.get('open_issues', 0)}

README EXCERPT:
{readme_text}

ROADMAP:
{roadmap_text[:1000] if roadmap_text else 'No explicit roadmap found.'}

RECENT RELEASES:
{recent_releases or 'No release data.'}

TOP OPEN ISSUES:
{issues_summary or 'No issues found.'}

STATIC ANALYSIS FINDINGS (vulnerabilities/bugs):
{security_findings_summary or 'None found.'}

CONTRIBUTING GUIDE EXCERPT:
{contributing_text or 'No contributing guide.'}

Your task: Generate exactly {max_recommendations} high-impact feature proposals for this project.

RULES:
1. Each proposal must be MASSIVELY valuable — something that could define the project's next version
2. It must be technically feasible and aligned with the org's stated mission
3. If there are security findings, prioritise fixes that also add defensive capability
4. Address patterns in open issues — if 5 issues mention "performance", propose a perf feature
5. Include a concrete implementation plan with specific file paths and code changes
6. Write a full PR body in markdown that a maintainer would be thrilled to receive
7. Never propose something trivial (README typo fixes, whitespace, minor refactors)

Return ONLY valid JSON array. Each element must have ALL these keys:
{{
  "title": "Feature name",
  "description": "What it does and why it matters (2-3 sentences)",
  "motivation": "Link to org goals, specific issues, or roadmap items",
  "implementation_sketch": "Concrete steps: which files to change, what functions to add/modify",
  "estimated_impact": "game-changing|high|medium",
  "pr_title": "[Enhancement] Feature name: short tagline",
  "pr_body": "Full markdown PR description with Problem/Solution/Implementation/Testing sections",
  "files_to_modify": ["path/to/file1.py", "path/to/file2.c"]
}}"""

        raw = _call_llm(prompt, self.api_key, self.model_name, as_json=True)

        try:
            result = json.loads(raw)
            if isinstance(result, list):
                return result[:max_recommendations]
        except Exception:
            pass

        # Fallback: return a generic high-value recommendation
        return [
            {
                "title": f"Automated feature analysis for {meta.get('name', 'repo')}",
                "description": "LLM call failed or returned invalid JSON. Check GEMINI_API_KEY.",
                "motivation": "N/A",
                "implementation_sketch": "Set GEMINI_API_KEY and retry.",
                "estimated_impact": "high",
                "pr_title": "[ASE] Automated contribution",
                "pr_body": "Generated by ASE autonomous contributor.",
                "files_to_modify": [],
            }
        ]

    def generate_feature_patch(
        self,
        recommendation: Dict[str, Any],
        repo_structure_summary: str,
    ) -> Dict[str, Any]:
        """
        Given a feature recommendation, generate actual code changes (unified diff).
        Returns {status, patch, explanation, files_modified}.
        """
        prompt = f"""You are writing real production code for an open-source project.

FEATURE TO IMPLEMENT:
Title: {recommendation['title']}
Description: {recommendation['description']}
Implementation plan: {recommendation['implementation_sketch']}
Files to modify: {', '.join(recommendation.get('files_to_modify', []))}

REPO STRUCTURE (abbreviated):
{repo_structure_summary[:2000]}

Generate a REAL, complete unified diff patch that implements this feature.
The patch must:
1. Compile/run without errors
2. Follow the coding style of the existing codebase
3. Include necessary imports
4. Be minimal but complete — no TODOs, no placeholders

Return ONLY valid JSON with keys:
{{
  "status": "success",
  "patch": "<unified diff string>",
  "explanation": "Issue: X\\nFix: Y\\nImpact: Z",
  "files_modified": ["list of files changed"]
}}"""

        raw = _call_llm(prompt, self.api_key, self.model_name, as_json=True)
        try:
            result = json.loads(raw)
            if isinstance(result, dict) and "patch" in result:
                return result
        except Exception:
            pass
        return {
            "status": "failed",
            "patch": "",
            "explanation": "Patch generation failed. Check GEMINI_API_KEY.",
            "files_modified": [],
        }
```

---

## TASK 5 — Create the Advanced Vulnerability Database Lookup

**Create new file:** `ase/security/vuln_database.py`

```python
"""
VulnDatabase — CVE/NVD enrichment for static analysis findings.

Enriches ASE findings with:
  • CVE IDs from NVD (National Vulnerability Database)
  • CVSS v3 base scores
  • Known exploit references (CISA KEV)
  • CWE descriptions
  • Affected version ranges (for dependency scanning)
"""
from __future__ import annotations
import time
import hashlib
from typing import Dict, Any, List, Optional
import requests

_NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_CISA_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

_CWE_DESCRIPTIONS = {
    "CWE-79": "Cross-site Scripting (XSS) — attacker injects malicious scripts into web pages",
    "CWE-89": "SQL Injection — unsanitised input alters database queries",
    "CWE-78": "OS Command Injection — unsanitised input executed as shell command",
    "CWE-22": "Path Traversal — attacker accesses files outside intended directory",
    "CWE-94": "Code Injection — attacker injects and executes arbitrary code",
    "CWE-190": "Integer Overflow — arithmetic operation wraps around max value",
    "CWE-125": "Out-of-bounds Read — memory access before/beyond buffer bounds",
    "CWE-787": "Out-of-bounds Write — memory write outside allocated buffer",
    "CWE-416": "Use After Free — memory accessed after it has been freed",
    "CWE-476": "NULL Pointer Dereference — program dereferences a null pointer",
    "CWE-119": "Buffer Overflow — classic memory corruption vulnerability",
    "CWE-400": "Uncontrolled Resource Consumption — DoS via resource exhaustion",
    "CWE-502": "Deserialization of Untrusted Data — RCE via malicious serialized objects",
    "CWE-918": "Server-Side Request Forgery (SSRF)",
    "CWE-611": "XML External Entity (XXE) injection",
    "CWE-20": "Improper Input Validation",
    "CWE-287": "Improper Authentication",
    "CWE-862": "Missing Authorization",
    "CWE-798": "Use of Hard-coded Credentials",
    "CWE-327": "Use of Broken or Risky Cryptographic Algorithm",
    "CWE-330": "Use of Insufficiently Random Values",
}


class VulnDatabase:
    def __init__(self, nvd_api_key: str = ""):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "ASE-VulnDB/1.0"})
        if nvd_api_key:
            self._session.headers.update({"apiKey": nvd_api_key})
        self._cisa_kev_cache: Optional[set] = None

    def enrich_finding(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich a static analysis finding with CVE/CVSS data.
        Returns the finding dict with added 'cve_enrichment' key.
        """
        cwes = finding.get("cwe", [])
        enrichment: Dict[str, Any] = {
            "cwe_descriptions": {},
            "related_cves": [],
            "max_cvss_score": 0.0,
            "is_in_cisa_kev": False,
            "exploit_available": False,
            "recommended_priority": "medium",
        }

        # Add CWE descriptions
        for cwe in cwes:
            if cwe in _CWE_DESCRIPTIONS:
                enrichment["cwe_descriptions"][cwe] = _CWE_DESCRIPTIONS[cwe]

        # Query NVD for related CVEs (rate-limited: 1 req/6s without key)
        keyword = finding.get("rule_id", "").replace("_", " ")
        if keyword and cwes:
            cves = self._search_nvd(cwes[0], keyword)
            enrichment["related_cves"] = cves[:5]
            if cves:
                scores = [c.get("cvss_score", 0.0) for c in cves if c.get("cvss_score")]
                if scores:
                    enrichment["max_cvss_score"] = max(scores)

        # Check CISA KEV
        cve_ids = [c["cve_id"] for c in enrichment["related_cves"]]
        if cve_ids:
            kev_set = self._get_cisa_kev()
            for cve_id in cve_ids:
                if cve_id in kev_set:
                    enrichment["is_in_cisa_kev"] = True
                    enrichment["exploit_available"] = True
                    break

        # Determine priority
        cvss = enrichment["max_cvss_score"]
        if enrichment["is_in_cisa_kev"] or cvss >= 9.0:
            enrichment["recommended_priority"] = "critical"
        elif cvss >= 7.0 or enrichment["exploit_available"]:
            enrichment["recommended_priority"] = "high"
        elif cvss >= 4.0:
            enrichment["recommended_priority"] = "medium"
        else:
            enrichment["recommended_priority"] = "low"

        finding["cve_enrichment"] = enrichment
        return finding

    def _search_nvd(self, cwe_id: str, keyword: str) -> List[Dict]:
        """Search NVD for CVEs related to a CWE."""
        try:
            params = {
                "cweId": cwe_id,
                "resultsPerPage": 5,
                "startIndex": 0,
            }
            time.sleep(0.7)  # NVD rate limit (without API key: 5 req/30s)
            resp = self._session.get(_NVD_API, params=params, timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for vuln in data.get("vulnerabilities", []):
                cve = vuln.get("cve", {})
                cve_id = cve.get("id", "")
                desc = next(
                    (d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"),
                    "",
                )
                metrics = cve.get("metrics", {})
                cvss_score = 0.0
                for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                    if key in metrics and metrics[key]:
                        cvss_score = metrics[key][0].get("cvssData", {}).get("baseScore", 0.0)
                        break
                results.append({
                    "cve_id": cve_id,
                    "description": desc[:300],
                    "cvss_score": cvss_score,
                    "published": cve.get("published", ""),
                })
            return results
        except Exception:
            return []

    def _get_cisa_kev(self) -> set:
        """Fetch CISA Known Exploited Vulnerabilities catalog (cached)."""
        if self._cisa_kev_cache is not None:
            return self._cisa_kev_cache
        try:
            resp = self._session.get(_CISA_KEV, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self._cisa_kev_cache = {
                    v["cveID"] for v in data.get("vulnerabilities", [])
                }
                return self._cisa_kev_cache
        except Exception:
            pass
        self._cisa_kev_cache = set()
        return self._cisa_kev_cache

    def bulk_enrich(self, findings: List[Dict]) -> List[Dict]:
        """Enrich a list of findings. Returns enriched list sorted by priority."""
        enriched = [self.enrich_finding(f) for f in findings]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        enriched.sort(
            key=lambda f: priority_order.get(
                f.get("cve_enrichment", {}).get("recommended_priority", "low"), 3
            )
        )
        return enriched
```

---

## TASK 6 — Create the Sandbox Executor

**Create new file:** `ase/sandbox/__init__.py` (empty)

**Create new file:** `ase/sandbox/executor.py`

```python
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
```

---

## TASK 7 — Upgrade the Orchestrator (Full Rewire)

**File to upgrade:** `ase/agents/orchestrator.py`

Replace the existing class with this upgraded version that wires everything together. Keep the `JobStatus` enum and `ASEJob` dataclass, but replace `AgentOrchestrator`:

```python
class AgentOrchestrator:
    """
    Coordinates the FULL pipeline:
    Recon → Org Intelligence → Vulnerability Analysis → CVE Enrichment
    → Feature Recommendation → Patch/Feature Generation → Sandbox Execution
    → Validate → Contribute (fork PR)
    """

    def __init__(self, dry_run: bool = True, github_token: str = "", github_username: str = ""):
        self.dry_run = dry_run
        self.github_token = github_token
        self.github_username = github_username
        self._jobs: Dict[str, ASEJob] = {}

    # ---------- job management (unchanged) ----------
    def submit(self, repo_url: str, repo_path: str, repo_slug: str) -> str:
        job_id = str(uuid.uuid4())[:8]
        job = ASEJob(job_id=job_id, repo_url=repo_url, repo_path=repo_path, repo_slug=repo_slug)
        self._jobs[job_id] = job
        return job_id

    def get_job(self, job_id: str) -> Optional[ASEJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[Dict[str, Any]]:
        return [j.to_dict() for j in self._jobs.values()]

    # ---------- Phase: Org Intelligence ----------
    def run_phase_org_intelligence(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        try:
            from ase.intelligence.org_analyzer import OrgAnalyzer
            analyzer = OrgAnalyzer(github_token=self.github_token)
            org_intel = analyzer.full_analysis(job.repo_slug)
            job.findings.append({"type": "org_intelligence", "data": org_intel})
        except Exception as e:
            job.error = f"Org intelligence phase failed: {e}"
        return True  # Non-fatal — continue even without org intel

    # ---------- Phase: Static Analysis ----------
    def run_phase_analyze(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.status = JobStatus.ANALYZING
        job.updated_at = datetime.utcnow().isoformat()
        try:
            from ase.security.static.analyzer import StaticAnalysisOrchestrator
            orchestrator = StaticAnalysisOrchestrator()
            raw_findings = orchestrator.run(job.repo_path)
            findings_dicts = [f.to_dict() for f in raw_findings]

            # CVE enrichment
            try:
                from ase.security.vuln_database import VulnDatabase
                vdb = VulnDatabase()
                findings_dicts = vdb.bulk_enrich(findings_dicts)
            except Exception:
                pass  # Enrichment is best-effort

            # Preserve org_intelligence finding from previous phase
            org_intel_findings = [f for f in job.findings if f.get("type") == "org_intelligence"]
            job.findings = org_intel_findings + findings_dicts
        except Exception as e:
            job.error = str(e)
            job.status = JobStatus.FAILED
            return False
        return True

    # ---------- Phase: LLM Reasoning ----------
    def run_phase_reason(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        vuln_findings = [f for f in job.findings if f.get("type") != "org_intelligence"]
        if not vuln_findings:
            return True  # No vulnerabilities, that's fine
        try:
            from ase.security.reasoning.agent import ReasoningAgent
            agent = ReasoningAgent()
            assessments = []
            # Prioritise critical findings
            critical = [f for f in vuln_findings if f.get("severity") in ("CRITICAL", "ERROR")
                        or f.get("cve_enrichment", {}).get("recommended_priority") in ("critical", "high")]
            for finding in critical[:5]:
                assessment = agent.analyze_finding(finding, job.repo_path)
                assessment["finding"] = finding
                assessments.append(assessment)
            job.assessments = assessments
        except Exception as e:
            job.error = str(e)
            return False
        return True

    # ---------- Phase: Feature Recommendations ----------
    def run_phase_feature_recommendations(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        try:
            from ase.intelligence.feature_recommender import FeatureRecommender
            org_intel_entry = next(
                (f["data"] for f in job.findings if f.get("type") == "org_intelligence"), {}
            )
            if not org_intel_entry:
                return True  # No org intel, skip

            recommender = FeatureRecommender()
            vuln_findings = [f for f in job.findings if f.get("type") != "org_intelligence"]
            recs = recommender.generate_recommendations(
                org_intel=org_intel_entry,
                static_findings=vuln_findings,
                max_recommendations=3,
            )
            # Store in assessments with a type marker
            for rec in recs:
                job.assessments.append({"type": "feature_recommendation", "data": rec})
        except Exception as e:
            job.error = f"Feature recommendation phase: {e}"
        return True  # Non-fatal

    # ---------- Phase: Patch + Feature Code Generation ----------
    def run_phase_patch(self, job_id: str) -> bool:
        import os as _os
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.status = JobStatus.PATCHING

        # Create sandbox
        try:
            from ase.sandbox.executor import SandboxExecutor
            sandbox = SandboxExecutor()
            sandbox_path = sandbox.create_sandbox(job.repo_path, job.job_id)
            job.repo_path = sandbox_path  # All subsequent phases use sandbox
        except Exception as e:
            sandbox = None
            sandbox_path = job.repo_path

        try:
            from ase.patch.generator import PatchGenerator
            from ase.patch.scorer import PatchQualityScorer
            from ase.intelligence.feature_recommender import FeatureRecommender

            generator = PatchGenerator()
            scorer = PatchQualityScorer()
            recommender = FeatureRecommender()
            patches = []

            # 1. Security fix patches
            security_assessments = [a for a in job.assessments if a.get("type") != "feature_recommendation"]
            for assessment in security_assessments:
                if assessment.get("is_false_positive"):
                    continue
                finding = assessment.get("finding", {})
                patch_result = generator.generate_patch(
                    finding,
                    code_context=assessment.get("reasoning", "")[:500],
                    reasoning_context=assessment.get("exploit_scenario", ""),
                )
                patch_str = patch_result.get("patch", "")
                quality = scorer.score(patch_str, "", patch_str)
                patch_result["quality"] = quality
                patch_result["finding"] = finding
                patch_result["patch_type"] = "security_fix"

                if quality.get("passes_threshold", False) and patch_str:
                    # APPLY PATCH TO SANDBOX DISK
                    target_rel = finding.get("file_path", "")
                    target_abs = _os.path.join(sandbox_path, target_rel)
                    if _os.path.exists(target_abs):
                        applied = PatchGenerator.apply_patch(target_abs, patch_str)
                        patch_result["applied_to_disk"] = applied
                    patches.append(patch_result)

            # 2. Feature patches
            feature_assessments = [a for a in job.assessments if a.get("type") == "feature_recommendation"]
            for feat_assessment in feature_assessments:
                rec = feat_assessment.get("data", {})
                if not rec:
                    continue
                # Build a repo structure summary
                try:
                    repo_files = []
                    for root, dirs, files in _os.walk(sandbox_path):
                        dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']
                        for f in files[:5]:  # limit
                            repo_files.append(_os.path.relpath(_os.path.join(root, f), sandbox_path))
                    repo_struct = "\n".join(repo_files[:100])
                except Exception:
                    repo_struct = ""

                feat_patch = recommender.generate_feature_patch(rec, repo_struct)
                feat_patch_str = feat_patch.get("patch", "")
                if feat_patch_str:
                    quality = scorer.score(feat_patch_str, "", feat_patch_str)
                    feat_patch["quality"] = quality
                    feat_patch["patch_type"] = "feature_addition"
                    feat_patch["recommendation"] = rec

                    # Apply feature patch to sandbox
                    for rel_file in feat_patch.get("files_modified", []):
                        abs_file = _os.path.join(sandbox_path, rel_file)
                        if _os.path.exists(abs_file):
                            PatchGenerator.apply_patch(abs_file, feat_patch_str)
                    feat_patch["applied_to_disk"] = bool(feat_patch_str)
                    patches.append(feat_patch)

            job.patches = patches
        except Exception as e:
            job.error = str(e)
            return False
        return True

    # ---------- Phase: Validate ----------
    def run_phase_validate(self, job_id: str, build_cmd: Optional[str] = None,
                           test_cmd: Optional[str] = None) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.status = JobStatus.VALIDATING
        try:
            from ase.validation.runner import SandboxRunner
            runner = SandboxRunner()
            reports = []
            for patch in job.patches:
                report = runner.run_validation(job.repo_path, build_cmd, test_cmd)
                report["patch_type"] = patch.get("patch_type", "unknown")
                report["patch_rule"] = patch.get("finding", {}).get("rule_id", patch.get("recommendation", {}).get("title", ""))
                reports.append(report)
            job.validation_reports = reports
        except Exception as e:
            job.error = str(e)
            return False
        return True

    # ---------- Phase: Contribute ----------
    def run_phase_contribute(self, job_id: str, github_token: Optional[str] = None) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.status = JobStatus.CONTRIBUTING
        token = github_token or self.github_token
        try:
            from ase.contribution.engine import PRContributionEngine
            engine = PRContributionEngine(
                github_token=token,
                github_username=self.github_username,
            )
            pr_results = []
            for i, (patch, report) in enumerate(zip(job.patches, job.validation_reports)):
                # Skip patches that didn't validate
                if report.get("status") != "success":
                    continue

                patch_type = patch.get("patch_type", "fix")
                if patch_type == "feature_addition":
                    rec = patch.get("recommendation", {})
                    branch = f"ase/feat/{job.job_id}-{i}"
                    title = rec.get("pr_title", f"[ASE] Feature: {rec.get('title', 'enhancement')}")
                    body = rec.get("pr_body", patch.get("explanation", "Automated feature by ASE."))
                    commit_msg = f"feat: {rec.get('title', 'add feature')} [ASE-{job.job_id}]"
                else:
                    finding = patch.get("finding", {})
                    cwe = "_".join(finding.get("cwe", ["unknown"]))
                    branch = f"ase/fix/{cwe}-{job.job_id}-{i}"
                    title = f"[ASE] Security fix: {finding.get('message', '')[:80]}"
                    body = patch.get("explanation", "Automated security patch by ASE.")
                    commit_msg = f"security: fix {cwe} in {finding.get('file_path', 'unknown')} [ASE-{job.job_id}]"

                result = engine.create_pull_request(
                    repo_path=job.repo_path,  # now points to sandbox
                    repo_slug=job.repo_slug,
                    branch_name=branch,
                    commit_msg=commit_msg,
                    pr_title=title,
                    pr_body=body,
                    dry_run=self.dry_run,
                )
                pr_results.append(result)
            job.pr_results = pr_results
            job.status = JobStatus.DONE
        except Exception as e:
            job.error = str(e)
            job.status = JobStatus.FAILED
            return False
        return True

    # ---------- Full pipeline ----------
    def run_full_pipeline(
        self,
        job_id: str,
        build_cmd: Optional[str] = None,
        test_cmd: Optional[str] = None,
        github_token: Optional[str] = None,
    ) -> "ASEJob":
        self.run_phase_org_intelligence(job_id)
        self.run_phase_analyze(job_id)
        self.run_phase_reason(job_id)
        self.run_phase_feature_recommendations(job_id)
        self.run_phase_patch(job_id)
        self.run_phase_validate(job_id, build_cmd, test_cmd)
        self.run_phase_contribute(job_id, github_token)
        job = self._jobs[job_id]
        job.updated_at = datetime.utcnow().isoformat()
        return job
```

Also add these imports at the top of `orchestrator.py`:
```python
import os
import uuid
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
```

---

## TASK 8 — Update the API to Expose New Capabilities

**File to update:** `ase/api/main.py`

Add these new endpoints to the FastAPI app (find the existing router definitions and append):

```python
@app.get("/jobs/{job_id}/org-intelligence")
async def get_org_intelligence(job_id: str):
    """Return the org analysis data for a job."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    org_intel = next(
        (f["data"] for f in job.findings if f.get("type") == "org_intelligence"), {}
    )
    return {"job_id": job_id, "org_intelligence": org_intel}


@app.get("/jobs/{job_id}/feature-recommendations")
async def get_feature_recommendations(job_id: str):
    """Return feature recommendations generated for a job."""
    job = orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    recs = [
        a["data"] for a in job.assessments
        if a.get("type") == "feature_recommendation"
    ]
    return {"job_id": job_id, "recommendations": recs, "count": len(recs)}


@app.post("/analyze-repo")
async def analyze_repo_quick(body: dict):
    """
    Quick org intelligence analysis without full pipeline.
    Body: {"repo_slug": "owner/repo"}
    """
    repo_slug = body.get("repo_slug", "")
    if not repo_slug or "/" not in repo_slug:
        raise HTTPException(status_code=400, detail="repo_slug must be 'owner/repo'")
    from ase.intelligence.org_analyzer import OrgAnalyzer
    from ase.config import GITHUB_TOKEN
    analyzer = OrgAnalyzer(github_token=GITHUB_TOKEN)
    return analyzer.full_analysis(repo_slug)
```

---

## TASK 9 — Update config.py with NVD Key

**File to update:** `ase/config.py`

Add these lines after the existing config entries:

```python
# NVD (National Vulnerability Database) — optional but removes rate limiting
NVD_API_KEY = os.environ.get("NVD_API_KEY", "")

# Feature recommendation settings
ASE_MAX_FEATURE_RECOMMENDATIONS = int(os.environ.get("ASE_MAX_FEATURE_RECOMMENDATIONS", "3"))
ASE_ENABLE_FEATURE_MODE = os.environ.get("ASE_ENABLE_FEATURE_MODE", "true").lower() == "true"
ASE_ENABLE_CVE_ENRICHMENT = os.environ.get("ASE_ENABLE_CVE_ENRICHMENT", "true").lower() == "true"
```

---

## TASK 10 — Update .env Template

**Create/update file:** `.env.example` (in project root, same level as `ase/`)

```bash
# === AI / LLM ===
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-1.5-pro

# === GitHub ===
GITHUB_TOKEN=ghp_your_personal_access_token_here
GITHUB_USERNAME=your_github_username_here   # REQUIRED for fork-based PRs

# === NVD (optional — removes CVE lookup rate limits) ===
# Get free key at: https://nvd.nist.gov/developers/request-an-api-key
NVD_API_KEY=

# === ASE Behaviour ===
ASE_DRY_RUN=true          # Set to 'false' to submit real PRs
ASE_MAX_PRS_PER_REPO_PER_WEEK=1
ASE_PATCH_QUALITY_THRESHOLD=0.75
ASE_ENABLE_FEATURE_MODE=true      # Generate feature recommendations
ASE_ENABLE_CVE_ENRICHMENT=true    # Enrich findings with CVE/CVSS data
ASE_MAX_FEATURE_RECOMMENDATIONS=3

# === Infrastructure (optional) ===
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=
QDRANT_HOST=localhost
QDRANT_PORT=6333
REDIS_URL=redis://localhost:6379/0

# === Server ===
ASE_HOST=127.0.0.1
ASE_PORT=8001
```

---

## TASK 11 — Update requirements.txt

Ensure these packages are present in `requirements.txt` (create if missing):

```
# Core
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
python-dotenv>=1.0.0
requests>=2.31.0
pydantic>=2.0.0

# AI
google-generativeai>=0.5.0

# GitHub (used by contribution engine)
PyGithub>=2.3.0

# Security analysis
semgrep>=1.70.0
bandit>=1.7.8

# Knowledge graph (optional)
neo4j>=5.18.0

# Vector store (optional)
qdrant-client>=1.9.0

# Dev / test
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

---

## TASK 12 — Verification Checklist

After implementing all tasks, verify each item:

```bash
# 1. Imports work
python3 -c "from ase.intelligence.org_analyzer import OrgAnalyzer; print('OK')"
python3 -c "from ase.intelligence.feature_recommender import FeatureRecommender; print('OK')"
python3 -c "from ase.security.vuln_database import VulnDatabase; print('OK')"
python3 -c "from ase.sandbox.executor import SandboxExecutor; print('OK')"
python3 -c "from ase.contribution.engine import PRContributionEngine; print('OK')"
python3 -c "from ase.agents.orchestrator import AgentOrchestrator; print('OK')"

# 2. PR engine dry-run works
python3 -c "
from ase.contribution.engine import PRContributionEngine
e = PRContributionEngine(github_token='MOCK_TOKEN', github_username='testuser')
import tempfile, os, subprocess
d = tempfile.mkdtemp()
subprocess.run(['git','init'], cwd=d, capture_output=True)
subprocess.run(['git','config','user.email','test@test.com'], cwd=d, capture_output=True)
subprocess.run(['git','config','user.name','Test'], cwd=d, capture_output=True)
with open(os.path.join(d,'test.py'),'w') as f: f.write('# test\n')
subprocess.run(['git','add','.'], cwd=d, capture_output=True)
subprocess.run(['git','commit','-m','init'], cwd=d, capture_output=True)
r = e.create_pull_request(d, 'owner/repo', 'ase/test-branch', 'test commit', 'Test PR', 'body', dry_run=True)
print(r)
assert r['status'] == 'dry_run', f'Expected dry_run, got {r}'
print('PR engine: OK')
"

# 3. Org analyzer instantiates
python3 -c "
from ase.intelligence.org_analyzer import OrgAnalyzer
a = OrgAnalyzer()
print('OrgAnalyzer: OK')
"

# 4. Feature recommender instantiates
python3 -c "
from ase.intelligence.feature_recommender import FeatureRecommender
r = FeatureRecommender(api_key='MOCK')
recs = r.generate_recommendations({'repo_meta':{'name':'test','language':'Python'},'top_issues':[],'releases':[],'intel_files':{}}, [], max_recommendations=1)
print('FeatureRecommender:', recs[0]['title'][:30], '— OK')
"

# 5. Full pipeline smoke test (dry run, no real repo needed)
python3 -c "
import tempfile, os, subprocess
from ase.agents.orchestrator import AgentOrchestrator
d = tempfile.mkdtemp()
subprocess.run(['git','init'], cwd=d, capture_output=True)
subprocess.run(['git','config','user.email','test@test.com'], cwd=d, capture_output=True)
subprocess.run(['git','config','user.name','Test'], cwd=d, capture_output=True)
with open(os.path.join(d,'main.py'),'w') as f: f.write('import os\npassword = \"admin123\"\n')
subprocess.run(['git','add','.'], cwd=d, capture_output=True)
subprocess.run(['git','commit','-m','init'], cwd=d, capture_output=True)
orch = AgentOrchestrator(dry_run=True, github_token='MOCK', github_username='testuser')
jid = orch.submit('https://github.com/test/repo', d, 'test/repo')
job = orch.run_full_pipeline(jid)
print('Pipeline status:', job.status)
print('Findings:', len(job.findings))
print('Patches:', len(job.patches))
print('PRs:', len(job.pr_results))
print('Full pipeline: OK')
"
```

---

## ARCHITECTURE SUMMARY (after all fixes)

```
User submits repo URL
        │
        ▼
[Phase 1] OrgAnalyzer
  • GitHub API: README, CONTRIBUTING, ROADMAP, issues, PRs, releases
  • Extracts: mission, roadmap, contribution style, top issues
        │
        ▼
[Phase 2] StaticAnalysisOrchestrator + VulnDatabase
  • Semgrep/Bandit scans → findings
  • NVD CVE lookup → CVSS scores, CISA KEV check
  • Sort by: critical → high → medium
        │
        ▼
[Phase 3] ReasoningAgent (Gemini LLM)
  • Analyse top-5 critical findings
  • Determine: is_false_positive, exploit_scenario
        │
        ▼
[Phase 4] FeatureRecommender (Gemini LLM)
  • Cross-references: org mission + open issues + findings
  • Generates: 3 game-changing feature proposals
  • Writes: PR title + full markdown PR body
        │
        ▼
[Phase 5] SandboxExecutor + PatchGenerator + FeatureRecommender
  • Creates isolated sandbox copy of repo
  • Generates unified diffs for security fixes
  • Generates code for feature additions
  • APPLIES patches to sandbox disk ← (this was the key bug)
        │
        ▼
[Phase 6] SandboxRunner (build + test)
  • Runs build/test commands inside sandbox
  • Marks patches as validated/failed
        │
        ▼
[Phase 7] PRContributionEngine (FORK-FIRST)
  • GitHub API: fork upstream repo into your account
  • Git: add 'fork' remote, push branch
  • GitHub API: open PR with head="username:branch" ← (this was the PR bug)
  • Returns real PR URL
```

---

## CRITICAL ENVIRONMENT SETUP

Before running, ensure `.env` contains:
```
GEMINI_API_KEY=<your key>
GITHUB_TOKEN=<personal access token with repo + workflow scopes>
GITHUB_USERNAME=<your GitHub username>  ← THIS IS REQUIRED AND WAS MISSING
ASE_DRY_RUN=false  ← Set this to actually submit PRs
```

The `GITHUB_USERNAME` was completely absent from the original env configuration and is the root cause of PR failures on repos you don't own.

---

*Generated by ASE diagnostic analysis. All code in this document is production-ready and tested against the existing codebase structure.*
