"""
LearningAgent — Phase 5.2
Polls open PRs for maintainer feedback, classifies comments,
stores positive/negative examples, and builds MaintainerProfiles.
"""
from __future__ import annotations
import re
import json
import sqlite3
from typing import Dict, Any, Optional
from enum import Enum

try:
    import requests as _requests
except ImportError:
    _requests = None  # type: ignore


class CommentClass(str, Enum):
    APPROVAL = "APPROVAL"
    CHANGE_REQUEST = "CHANGE_REQUEST"
    REJECTION = "REJECTION"
    QUESTION = "QUESTION"
    UNKNOWN = "UNKNOWN"


_APPROVAL_KEYWORDS = ["lgtm", "looks good", "approved", "merging", "nice fix", "thank you", "merged"]
_REJECTION_KEYWORDS = ["nack", "not this way", "revert", "rejected", "closing", "won't fix", "wrong approach"]
_CHANGE_REQUEST_KEYWORDS = ["please change", "needs to", "should be", "fix the", "update the", "missing", "change request"]
_QUESTION_KEYWORDS = ["why", "what", "how", "?", "can you explain", "what about", "have you considered"]


class LearningAgent:
    def __init__(self, db_path: str = "ase_patches.db", github_token: Optional[str] = None):
        self.github_token = github_token
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self):
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS pr_feedback (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_slug   TEXT,
            pr_number   INTEGER,
            comment     TEXT,
            classif     TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS maintainer_profiles (
            repo_slug       TEXT PRIMARY KEY,
            preferred_style TEXT,
            red_lines       TEXT,
            positive_count  INTEGER DEFAULT 0,
            negative_count  INTEGER DEFAULT 0,
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        """)
        self.db.commit()

    def classify_comment(self, comment_text: str) -> CommentClass:
        text_lower = comment_text.lower()
        if any(k in text_lower for k in _REJECTION_KEYWORDS):
            return CommentClass.REJECTION
        if any(k in text_lower for k in _CHANGE_REQUEST_KEYWORDS):
            return CommentClass.CHANGE_REQUEST
        if any(k in text_lower for k in _APPROVAL_KEYWORDS):
            return CommentClass.APPROVAL
        if any(k in text_lower for k in _QUESTION_KEYWORDS):
            return CommentClass.QUESTION
        return CommentClass.UNKNOWN

    def process_comment(self, repo_slug: str, pr_number: int,
                        comment: str, patch_pair_id: Optional[str] = None) -> Dict[str, Any]:
        classif = self.classify_comment(comment)

        # Store raw feedback
        self.db.execute(
            "INSERT INTO pr_feedback (repo_slug, pr_number, comment, classif) VALUES (?, ?, ?, ?)",
            (repo_slug, pr_number, comment, classif.value),
        )

        # Update maintainer profile counters
        if classif in (CommentClass.APPROVAL,):
            self._update_profile(repo_slug, positive=True)
        elif classif in (CommentClass.REJECTION,):
            self._update_profile(repo_slug, positive=False)
            if patch_pair_id:
                self._mark_pair(patch_pair_id, accepted=0)

        self.db.commit()
        return {
            "classification": classif.value,
            "repo_slug": repo_slug,
            "pr_number": pr_number,
        }

    def _update_profile(self, repo_slug: str, positive: bool):
        col = "positive_count" if positive else "negative_count"
        self.db.execute(
            f"INSERT INTO maintainer_profiles (repo_slug, {col}) VALUES (?, 1) "
            f"ON CONFLICT(repo_slug) DO UPDATE SET {col} = {col} + 1",
            (repo_slug,),
        )

    def _mark_pair(self, pair_id: str, accepted: int):
        self.db.execute(
            "UPDATE patch_pairs SET accepted = ? WHERE id = ?", (accepted, pair_id)
        )

    def get_profile(self, repo_slug: str) -> Dict[str, Any]:
        row = self.db.execute(
            "SELECT * FROM maintainer_profiles WHERE repo_slug = ?", (repo_slug,)
        ).fetchone()
        if row:
            return {k: row[k] for k in row.keys()}
        return {"repo_slug": repo_slug, "positive_count": 0, "negative_count": 0}

    def poll_pr_comments(self, repo_slug: str, pr_number: int) -> list:
        """Poll GitHub API for new comments on a PR."""
        if _requests is None or not self.github_token:
            return []
        url = f"https://api.github.com/repos/{repo_slug}/issues/{pr_number}/comments"
        headers = {"Authorization": f"token {self.github_token}"}
        try:
            resp = _requests.get(url, headers=headers)
            if resp.status_code == 200:
                return [c["body"] for c in resp.json()]
        except Exception:
            pass
        return []
