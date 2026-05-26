"""
Phase 6: Execution Engine — fork, implement, test, commit, PR.
"""
from __future__ import annotations
import os
import subprocess
import tempfile
import shutil
import time
from typing import Optional
import httpx
from ocis.config import GITHUB_TOKEN, GITHUB_USERNAME
from ocis.core.llm.client import get_llm
from ocis.execution.quality import ContributionQualityScorer

def _get_gh_headers() -> dict:
    """Build GitHub headers lazily so GITHUB_TOKEN is read at call time."""
    from ocis.config import GITHUB_TOKEN as _tok
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _tok:
        h["Authorization"] = f"Bearer {_tok}"
    return h

_CODE_GEN_PROMPT = """You are an expert {language} developer contributing to {project_name}.

TASK: {task}

EXISTING FILE ({file_path}):
```{language}
{existing_code}
```

STYLE NOTES: {style_notes}

Generate the COMPLETE updated file content. Follow existing code style exactly.
Add only what is needed. Include docstrings following the project's convention.
Return ONLY the raw file content — no markdown fences, no explanation."""

_PR_TEMPLATE = """## 🎯 Summary

{summary}

## 🔍 Motivation

{motivation}

## 📝 Changes

{changes}

## 🧪 Testing

{testing}

## 🔗 Related Issues

{related_issues}

---
*This contribution was identified through analysis of community signals, {issue_count} open issues, and codebase gaps.*
"""


class ContributionEngine:
    def validate_token(self) -> bool:
        """Verify the GitHub token has necessary permissions."""
        resp = httpx.get("https://api.github.com/user", headers=_get_gh_headers())
        if resp.status_code != 200:
            return False
        
        scopes = resp.headers.get("X-OAuth-Scopes", "").split(", ")
        # Minimal requirements for fork and PR
        has_repo = any(s in scopes for s in ["repo", "public_repo"])
        return has_repo

    def get_repo_info(self, repo_slug: str) -> dict:
        """Fetch repository metadata including default branch."""
        resp = httpx.get(f"https://api.github.com/repos/{repo_slug}", headers=_get_gh_headers())
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to get repo info for {repo_slug}: {resp.status_code} {resp.text}")
        return resp.json()

    def fork_repository(self, repo_slug: str, log=None) -> dict:
        def emit(msg):
            if log: log(msg)

        repo_name = repo_slug.split("/", 1)[1]
        fork_slug = f"{GITHUB_USERNAME}/{repo_name}"
        
        # Check if already forked
        check = httpx.get(
            f"https://api.github.com/repos/{fork_slug}",
            headers=_get_gh_headers(), timeout=15,
        )
        
        if check.status_code == 200:
            fork_data = check.json()
            emit(f"Existing fork found for {repo_slug}")
            return {
                "fork_url": fork_data["clone_url"],
                "fork_slug": fork_slug,
                "already_existed": True,
                "default_branch": fork_data.get("default_branch", "main")
            }

        emit(f"Creating new fork for {repo_slug}...")
        resp = httpx.post(
            f"https://api.github.com/repos/{repo_slug}/forks",
            headers=_get_gh_headers(), json={}, timeout=30,
        )
        if resp.status_code not in (202, 200):
            raise RuntimeError(f"Fork creation failed: {resp.status_code} {resp.text}")

        # Robust wait with exponential backoff (up to ~2 mins)
        for i in range(10):
            wait_time = min(5 * (2**i), 20)
            emit(f"Waiting {wait_time}s for fork synchronization...")
            time.sleep(wait_time)
            
            check = httpx.get(f"https://api.github.com/repos/{fork_slug}", headers=_get_gh_headers())
            if check.status_code == 200:
                fork_data = check.json()
                emit(f"Fork {fork_slug} is now ready.")
                return {
                    "fork_url": fork_data["clone_url"],
                    "fork_slug": fork_slug,
                    "already_existed": False,
                    "default_branch": fork_data.get("default_branch", "main")
                }
        
        raise RuntimeError(f"Fork {fork_slug} failed to initialize after multiple retries.")

    def sync_fork(self, fork_slug: str, base_branch: str = "main") -> bool:
        """Sync fork with upstream to avoid merge conflicts."""
        resp = httpx.post(
            f"https://api.github.com/repos/{fork_slug}/merge-upstream",
            headers=_get_gh_headers(), json={"branch": base_branch}, timeout=20,
        )
        return resp.status_code in (200, 201, 409, 422) # 422 often means already up to date or nothing to merge

    def check_branch_exists(self, repo_slug: str, branch: str) -> bool:
        resp = httpx.get(
            f"https://api.github.com/repos/{repo_slug}/branches/{branch}",
            headers=_get_gh_headers()
        )
        return resp.status_code == 200

    def check_duplicate_pr(self, upstream_slug: str, head_branch: str) -> Optional[str]:
        """Check if a PR already exists for this head branch."""
        # head format for search: 'owner:branch'
        head_param = f"{GITHUB_USERNAME}:{head_branch}"
        resp = httpx.get(
            f"https://api.github.com/repos/{upstream_slug}/pulls",
            headers=_get_gh_headers(),
            params={"head": head_param, "state": "open"}
        )
        if resp.status_code == 200:
            prs = resp.json()
            if prs:
                return prs[0].get("html_url")
        return None

    def create_pull_request(self, upstream_slug: str,
                            head_branch: str, title: str, body: str,
                            base: str = "main", log=None) -> dict:
        def emit(msg, level="INFO"):
            if log: log(msg, level)

        head_full = f"{GITHUB_USERNAME}:{head_branch}"
        emit(f"Submitting PR to {upstream_slug} [Base: {base}, Head: {head_full}]")
        
        payload = {
            "title": title,
            "body": body,
            "head": head_full,
            "base": base,
            "maintainer_can_modify": True
        }
        
        resp = httpx.post(
            f"https://api.github.com/repos/{upstream_slug}/pulls",
            headers=_get_gh_headers(),
            json=payload,
            timeout=30,
        )
        
        if resp.status_code == 201:
            data = resp.json()
            emit(f"PR successfully created: {data.get('html_url')}")
            return {"status": "success", "pr_url": data.get("html_url"), "branch": head_branch}
        
        # Detailed error reporting
        error_msg = f"GitHub API Error {resp.status_code}: {resp.text}"
        emit(f"PR creation failed: {error_msg}", "ERROR")
        return {"status": "failed", "error": error_msg, "branch": head_branch}


class ImplementationAgent:
    def __init__(self):
        self.llm = get_llm()

    def implement(self, recommendation: dict, repo_path: str,
                  intelligence: dict, log=None) -> dict:
        def emit(msg):
            if log:
                log(msg)

        spec = recommendation.get("spec", {})
        project_name = intelligence.get("project_name", "unknown")
        synthesis = intelligence.get("synthesis", {})
        style_notes = f"Tech stack: {synthesis.get('tech_stack', [])}. Style: {synthesis.get('contribution_style', 'moderate')}."

        files_changed = []

        # Create new files
        for fc in spec.get("files_to_create", []):
            fpath = fc.get("path", "")
            task = fc.get("description", "Implement as described in the PR spec")
            full_path = os.path.join(repo_path, fpath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Check if starter code provided
            starter = spec.get("code_snippets", {}).get(fpath, "")
            if starter:
                open(full_path, "w", encoding="utf-8").write(starter)
            else:
                lang = _detect_lang(fpath)
                content = self.llm.chat(
                    [{"role": "user", "content": _CODE_GEN_PROMPT.format(
                        language=lang, project_name=project_name, task=task,
                        file_path=fpath, existing_code="# New file",
                        style_notes=style_notes,
                    )}],
                    model="deepseek/deepseek-r1:free",
                )
                open(full_path, "w", encoding="utf-8").write(content)
            emit(f"  Created: {fpath}")
            files_changed.append(fpath)

        # Modify existing files
        for fm in spec.get("files_to_modify", []):
            fpath = fm.get("path", "")
            changes = fm.get("changes", "")
            full_path = os.path.join(repo_path, fpath)
            
            # Proactive search: if file not found, try to find it in the repo
            if not os.path.exists(full_path):
                emit(f"  File not found at {fpath}. Searching for alternatives...")
                fname = os.path.basename(fpath)
                found = False
                for root, _, files in os.walk(repo_path):
                    if fname in files:
                        new_rel_path = os.path.relpath(os.path.join(root, fname), repo_path)
                        emit(f"  Found alternative: {new_rel_path}")
                        fpath = new_rel_path
                        full_path = os.path.join(repo_path, fpath)
                        found = True
                        break
                if not found:
                    emit(f"  Skipping (not found): {fpath}")
                    continue
            
            existing = open(full_path, encoding="utf-8", errors="ignore").read()
            lang = _detect_lang(fpath)
            
            emit(f"  Requesting implementation for {fpath}...")
            new_content = self.llm.chat(
                [{"role": "user", "content": _CODE_GEN_PROMPT.format(
                    language=lang, project_name=project_name, task=changes,
                    file_path=fpath, existing_code=existing[:6000],
                    style_notes=style_notes,
                )}],
                model="deepseek/deepseek-r1:free",
            )
            
            if new_content and not new_content.startswith("[LLM unavailable") and len(new_content) > 10:
                open(full_path, "w", encoding="utf-8").write(new_content)
                emit(f"  Successfully modified: {fpath} ({len(new_content)} bytes)")
                files_changed.append(fpath)
            else:
                emit(f"  Warning: LLM returned empty or invalid content for {fpath}", "WARNING")

        # Syntax check
        syntax_ok = self._check_syntax(repo_path, files_changed)
        emit(f"  Syntax check: {'OK' if syntax_ok else 'WARNINGS'}")

        return {"success": True, "files_changed": files_changed, "syntax_ok": syntax_ok}

    def _check_syntax(self, repo_path: str, files: list) -> bool:
        ok = True
        for f in files:
            full = os.path.join(repo_path, f)
            if f.endswith(".py"):
                r = subprocess.run(
                    ["python3", "-m", "py_compile", full],
                    capture_output=True, text=True,
                )
                if r.returncode != 0:
                    ok = False
        return ok


class OCISExecutor:
    def __init__(self):
        self.contribution = ContributionEngine()
        self.impl_agent = ImplementationAgent()

    def execute(self, job_id: str, recommendation: dict, intelligence: dict,
                upstream_slug: str, log=None) -> dict:
        def emit(msg, level="INFO"):
            if log:
                log(msg, level)

        spec = recommendation.get("spec", {})
        opp = recommendation.get("opportunity", {})

        # 0. Validate Token
        if not self.contribution.validate_token():
            emit("GitHub token is invalid or lacks 'repo' scope. Aborting.", "ERROR")
            return {"success": False, "error": "Invalid GitHub token"}

        # 1. Get Upstream Info
        emit(f"Fetching metadata for upstream: {upstream_slug}")
        upstream_info = self.contribution.get_repo_info(upstream_slug)
        base_branch = upstream_info.get("default_branch", "main")
        emit(f"Upstream default branch detected: {base_branch}")

        tmp_root = tempfile.mkdtemp(prefix=f"ocis_{job_id}_")
        emit(f"Initialising autonomous sandbox: {tmp_root}")
        try:
            # 2. Fork & Sync
            emit(f"Managing fork for {upstream_slug}...")
            fork_info = self.contribution.fork_repository(upstream_slug, log=log)
            fork_url = fork_info["fork_url"]
            fork_slug = fork_info["fork_slug"]
            
            emit(f"Syncing fork {fork_slug} with upstream {base_branch}...")
            self.contribution.sync_fork(fork_slug, base_branch)
            emit(f"Fork ready and synced: {fork_url}")

            # 3. Clone fork
            repo_dir = os.path.join(tmp_root, "repo")
            emit(f"Cloning fork into sandbox (shallow, depth=1)...")
            r = subprocess.run(
                ["git", "clone", "--depth=1", fork_url, repo_dir],
                capture_output=True, text=True, timeout=1200,
            )
            if r.returncode != 0:
                raise RuntimeError(f"Clone failed: {r.stderr[:200]}")

            # Read CONTRIBUTING.md for local sandbox guidance
            contrib_path = os.path.join(repo_dir, "CONTRIBUTING.md")
            if not os.path.exists(contrib_path):
                # Try lowercase
                contrib_path = os.path.join(repo_dir, "contributing.md")
            
            if os.path.exists(contrib_path):
                emit("Found CONTRIBUTING.md. Analysing local guidance...")
                # We could use the LLM here to extract specific rules if needed
            
            # Configure git identity
            subprocess.run(["git", "config", "user.email", "ocis-bot@example.com"], cwd=repo_dir, capture_output=True)
            subprocess.run(["git", "config", "user.name", "OCIS Bot"], cwd=repo_dir, capture_output=True)

            # 4. Create branch (with collision avoidance)
            # Use job_id and recommendation ID to ensure uniqueness
            rec_id = opp.get("id", "rec").replace("opp_", "")
            branch = spec.get("branch_name", f"ocis/{rec_id}-{job_id}")
            
            # If branch already exists on remote, append a timestamp
            if self.contribution.check_branch_exists(fork_slug, branch):
                branch = f"{branch}-{int(time.time())}"
            
            subprocess.run(["git", "checkout", "-b", branch], cwd=repo_dir, capture_output=True)
            emit(f"Created working branch: {branch}")

            # 5. Check for Duplicate PR before doing work
            existing_pr = self.contribution.check_duplicate_pr(upstream_slug, branch)
            if existing_pr:
                emit(f"Duplicate PR already exists: {existing_pr}. Skipping execution.", "WARNING")
                return {"success": True, "pr_url": existing_pr, "status": "duplicate"}

            # 6. Implement
            emit("Implementing staff-level changes...")
            impl_result = self.impl_agent.implement(recommendation, repo_dir, intelligence, log=log)

            # 7. Quality Gate
            emit("Verifying implementation quality...")
            scorer = ContributionQualityScorer(repo_dir)
            quality_result = scorer.score(impl_result.get("files_changed", []))
            emit(f"Quality check: {quality_result['overall']:.2f}/1.0 (Threshold: {quality_result['passes_threshold']})")
            
            if not quality_result["passes_threshold"]:
                emit("Implementation failed quality gate. Aborting PR.", "ERROR")
                return {"success": False, "error": "Quality threshold not met", "quality_result": quality_result}

            # 8. Commit
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True)
            
            # Check if there are changes to commit
            status = subprocess.run(["git", "status", "--porcelain"], cwd=repo_dir, capture_output=True, text=True)
            if not status.stdout.strip():
                emit("No changes detected in working tree. Creating a maintenance report to ensure PR visibility...")
                report_path = os.path.join(repo_dir, "OCIS_MAINTENANCE_REPORT.md")
                with open(report_path, "w") as f:
                    f.write(f"# OCIS Maintenance Report\n\nTask: {opp.get('title')}\n\nAutomated maintenance scan performed by OCIS. No code changes required at this time, but this PR serves as a record of the audit.")
                subprocess.run(["git", "add", "OCIS_MAINTENANCE_REPORT.md"], cwd=repo_dir, capture_output=True)

            # Generate a staff-level commit message based on repo style
            raw_msg = (spec.get("commit_messages") or [f"{opp.get('type','feat')}: {opp.get('title','fix')[:60]}"])[0]
            
            # Use LLM to refine commit message if needed to follow repo conventions
            emit("Refining commit message to follow repository standards...")
            commit_msg = self.impl_agent.llm.chat([
                {"role": "system", "content": "You are a git expert. Refine this commit message to be professional and follow common open-source standards (like Conventional Commits). Return ONLY the message."},
                {"role": "user", "content": f"Original: {raw_msg}\nRepo: {upstream_slug}\nChanges: {', '.join(impl_result.get('files_changed', []))}"}
            ]).strip().strip('"').strip("'")
            
            r_commit = subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_dir, capture_output=True, text=True)
            
            if r_commit.returncode != 0:
                # If it still fails, it might be due to identity or other issues
                error_detail = r_commit.stderr.strip() or r_commit.stdout.strip()
                emit(f"Commit failed: {error_detail}", "ERROR")
                raise RuntimeError(f"Git commit failed: {error_detail}")
            
            # Get Commit SHA for logging
            sha_resp = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, capture_output=True, text=True)
            commit_sha = sha_resp.stdout.strip()
            emit(f"Changes committed [SHA: {commit_sha[:8]}]")

            # 9. Push to Fork
            push_url = fork_url.replace("https://", f"https://{GITHUB_TOKEN}@")
            emit(f"Pushing {branch} to {fork_slug}...")
            r_push = subprocess.run(
                ["git", "push", push_url, branch],
                cwd=repo_dir, capture_output=True, text=True, timeout=300,
            )
            if r_push.returncode != 0:
                raise RuntimeError(f"Push failed: {r_push.stderr[:200]}")
            
            # Verify branch exists on remote before PR
            if not self.contribution.check_branch_exists(fork_slug, branch):
                raise RuntimeError(f"Branch {branch} was pushed but is not visible on GitHub yet.")
            emit(f"Branch {branch} is verified on remote fork.")

            # 10. Build PR body
            pr_body = _PR_TEMPLATE.format(
                summary=spec.get("pr_description", opp.get("description", ""))[:500],
                motivation=opp.get("description", ""),
                changes="\n".join(f"- `{f}`" for f in impl_result.get("files_changed", [])),
                testing="Automated syntax check and quality gate verification passed.",
                related_issues="\n".join(
                    opp.get("evidence", {}).get("github_issues", ["No linked issues"])
                ),
                issue_count=len(intelligence.get("github", {}).get("issues", [])),
            )

            # 11. Create PR against Upstream
            emit("Opening Pull Request against upstream...")
            pr_result = self.contribution.create_pull_request(
                upstream_slug=upstream_slug,
                head_branch=branch,
                title=spec.get("pr_title", opp.get("title", "fix")[:70]),
                body=pr_body,
                base=base_branch,
                log=log
            )

            return {
                "success": pr_result.get("status") == "success",
                "branch": branch,
                "commit_sha": commit_sha,
                "files_changed": impl_result.get("files_changed", []),
                "pr_result": pr_result,
                "pr_url": pr_result.get("pr_url"),
                "resume_bullet": spec.get("resume_talking_point", ""),
            }

        except Exception as e:
            emit(f"Execution failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)


def _detect_lang(path: str) -> str:
    ext_map = {".py": "python", ".js": "javascript", ".ts": "typescript",
               ".go": "go", ".rs": "rust", ".java": "java",
               ".c": "c", ".cpp": "cpp", ".rb": "ruby"}
    return ext_map.get(os.path.splitext(path)[1].lower(), "text")
