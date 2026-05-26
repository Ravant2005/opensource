"""
HistoricalPatchDataset — Phase 3.1
SQLite-backed store of CVE-fix commit pairs, scraped from GitHub commit search API.
Also provides PatchStyleExtractor for per-repo coding convention learning.
"""
from __future__ import annotations
import re
import json
import sqlite3
import hashlib
import os
from typing import List, Dict, Any, Optional
from pathlib import Path

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------
_DDL = """
CREATE TABLE IF NOT EXISTS patch_pairs (
    id            TEXT PRIMARY KEY,
    repo_slug     TEXT NOT NULL,
    commit_sha    TEXT NOT NULL,
    commit_msg    TEXT,
    pr_body       TEXT,
    cve_ids       TEXT,        -- JSON list
    vulnerable    TEXT,        -- code before
    fixed         TEXT,        -- code after
    context       TEXT,        -- surrounding file context
    accepted      INTEGER,     -- 1 = merged, 0 = rejected, NULL = unknown
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS repo_styles (
    repo_slug     TEXT PRIMARY KEY,
    error_style   TEXT,        -- "goto" | "early_return" | "exceptions"
    naming_style  TEXT,        -- "snake_case" | "camelCase" | "PascalCase"
    comment_style TEXT,        -- "kernel" | "javadoc" | "inline"
    fix_patterns  TEXT,        -- JSON dict: {cwe: most_common_fix_pattern}
    updated_at    TEXT DEFAULT (datetime('now'))
);
"""

_SECURITY_SEARCH_TERMS = [
    "fix CVE", "security fix", "buffer overflow", "use after free",
    "sql injection", "command injection", "null pointer", "integer overflow",
    "memory leak", "out of bounds",
]


class HistoricalPatchDataset:
    def __init__(self, db_path: str = "ase_patches.db"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_DDL)
        self._conn.commit()

    # ------------------------------------------------------------------
    # GitHub ingestion
    # ------------------------------------------------------------------
    def ingest_from_github(
        self,
        repo_slug: str,
        github_token: Optional[str] = None,
        max_commits: int = 100,
    ) -> int:
        """
        Searches GitHub commit history for security-fix commits and stores
        (vulnerable, fixed, context) triples. Returns count of new pairs added.
        """
        if _requests is None:
            raise ImportError("requests library is required for GitHub ingestion.")

        token = github_token or os.environ.get("GITHUB_TOKEN", "")
        headers = {"Authorization": f"token {token}"} if token else {}
        added = 0

        for term in _SECURITY_SEARCH_TERMS[:3]:  # limit API calls
            url = f"https://api.github.com/search/commits?q={term}+repo:{repo_slug}&per_page=30"
            try:
                resp = _requests.get(url, headers={**headers, "Accept": "application/vnd.github.cloak-preview+json"})
                if resp.status_code != 200:
                    continue
                items = resp.json().get("items", [])
            except Exception:
                continue

            for item in items[:max_commits]:
                sha = item["sha"]
                msg = item["commit"]["message"]
                # Fetch diff
                diff_url = f"https://api.github.com/repos/{repo_slug}/commits/{sha}"
                try:
                    diff_resp = _requests.get(diff_url, headers=headers)
                    if diff_resp.status_code != 200:
                        continue
                    files = diff_resp.json().get("files", [])
                except Exception:
                    continue

                for f in files:
                    patch = f.get("patch", "")
                    if not patch:
                        continue
                    vulnerable, fixed = self._split_diff(patch)
                    cve_ids = re.findall(r"CVE-\d{4}-\d+", msg, re.IGNORECASE)
                    pair_id = hashlib.sha256(f"{sha}:{f['filename']}".encode()).hexdigest()[:20]
                    try:
                        self._conn.execute(
                            "INSERT OR IGNORE INTO patch_pairs "
                            "(id, repo_slug, commit_sha, commit_msg, cve_ids, vulnerable, fixed, accepted) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                            (pair_id, repo_slug, sha, msg, json.dumps(cve_ids), vulnerable, fixed),
                        )
                        added += 1
                    except sqlite3.Error:
                        pass

        self._conn.commit()
        return added

    def _split_diff(self, patch: str):
        """Split a unified diff patch into (vulnerable, fixed) code strings."""
        removed, added = [], []
        for line in patch.splitlines():
            if line.startswith("-") and not line.startswith("---"):
                removed.append(line[1:])
            elif line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
        return "\n".join(removed), "\n".join(added)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------
    def find_similar_fixes(self, cwe_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM patch_pairs WHERE cve_ids LIKE ? AND accepted = 1 LIMIT ?",
            (f"%{cwe_id}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def store_pair(self, repo_slug: str, vulnerable: str, fixed: str,
                   commit_msg: str, accepted: int, cve_ids: Optional[List[str]] = None) -> str:
        pair_id = hashlib.sha256(f"{repo_slug}:{vulnerable[:80]}".encode()).hexdigest()[:20]
        self._conn.execute(
            "INSERT OR REPLACE INTO patch_pairs "
            "(id, repo_slug, commit_sha, commit_msg, cve_ids, vulnerable, fixed, accepted) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pair_id, repo_slug, "", commit_msg, json.dumps(cve_ids or []), vulnerable, fixed, accepted),
        )
        self._conn.commit()
        return pair_id

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# PatchStyleExtractor
# ---------------------------------------------------------------------------
class PatchStyleExtractor:
    """
    Learns per-repo coding conventions from a set of source files or diffs.
    """

    _ERROR_GOTO = re.compile(r"\bgoto\s+\w+_(?:err|error|fail|out)\b")
    _ERROR_RETURN = re.compile(r"\breturn\s+(?:-\d+|NULL|nullptr|false|False|nil)\b")
    _ERROR_EXCEPTION = re.compile(r"\braise\b|\bthrow\b")
    _SNAKE = re.compile(r"^[a-z][a-z0-9_]+$")
    _CAMEL = re.compile(r"^[a-z][a-zA-Z0-9]+[A-Z][a-zA-Z0-9]*$")
    _PASCAL = re.compile(r"^[A-Z][a-zA-Z0-9]+$")
    _KERNEL_COMMENT = re.compile(r"/\*\s*\n(\s*\*.*\n)+\s*\*/")
    _JAVADOC = re.compile(r"/\*\*")
    _INLINE = re.compile(r"//|#")

    def extract(self, code_samples: List[str]) -> Dict[str, str]:
        """
        Accepts a list of source code strings and returns a style dict.
        """
        combined = "\n".join(code_samples)
        return {
            "error_style": self._detect_error_style(combined),
            "naming_style": self._detect_naming_style(combined),
            "comment_style": self._detect_comment_style(combined),
        }

    def _detect_error_style(self, code: str) -> str:
        goto = len(self._ERROR_GOTO.findall(code))
        ret = len(self._ERROR_RETURN.findall(code))
        exc = len(self._ERROR_EXCEPTION.findall(code))
        mx = max(goto, ret, exc)
        if mx == 0:
            return "unknown"
        if mx == goto:
            return "goto"
        if mx == exc:
            return "exceptions"
        return "early_return"

    def _detect_naming_style(self, code: str) -> str:
        tokens = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]{2,})\b", code)
        snake = sum(1 for t in tokens if self._SNAKE.match(t))
        camel = sum(1 for t in tokens if self._CAMEL.match(t))
        pascal = sum(1 for t in tokens if self._PASCAL.match(t))
        mx = max(snake, camel, pascal)
        if mx == snake:
            return "snake_case"
        if mx == camel:
            return "camelCase"
        return "PascalCase"

    def _detect_comment_style(self, code: str) -> str:
        if self._JAVADOC.search(code):
            return "javadoc"
        if self._KERNEL_COMMENT.search(code):
            return "kernel"
        return "inline"
