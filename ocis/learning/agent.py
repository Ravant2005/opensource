"""
OCIS Learning Agent — tracks PR outcomes, builds maintainer profiles,
feeds signal back into opportunity scoring weights.
"""
from __future__ import annotations
import sqlite3
import json
from typing import Optional

_DDL = """
CREATE TABLE IF NOT EXISTS pr_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_slug TEXT, pr_url TEXT, pr_title TEXT,
    status TEXT,  -- merged|closed|open
    days_to_merge INTEGER,
    resume_bullet TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS maintainer_profiles (
    repo_slug TEXT PRIMARY KEY,
    preferred_types TEXT,  -- JSON list of contribution types that got merged
    avg_days_to_merge REAL,
    merge_rate REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS scoring_weights (
    id INTEGER PRIMARY KEY,
    impact_w REAL DEFAULT 0.35,
    novelty_w REAL DEFAULT 0.30,
    visibility_w REAL DEFAULT 0.20,
    difficulty_w REAL DEFAULT 0.15,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


class LearningAgent:
    def __init__(self, db_path: str = "ocis_learning.db"):
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_DDL)
        self._db.commit()

    def record_outcome(self, repo_slug: str, pr_url: str, pr_title: str,
                       status: str, days_to_merge: Optional[int] = None,
                       resume_bullet: str = ""):
        self._db.execute(
            "INSERT INTO pr_outcomes (repo_slug, pr_url, pr_title, status, days_to_merge, resume_bullet) "
            "VALUES (?,?,?,?,?,?)",
            (repo_slug, pr_url, pr_title, status, days_to_merge, resume_bullet)
        )
        self._db.commit()
        self._update_profile(repo_slug)

    def _update_profile(self, repo_slug: str):
        rows = self._db.execute(
            "SELECT status, days_to_merge FROM pr_outcomes WHERE repo_slug=?", (repo_slug,)
        ).fetchall()
        total = len(rows)
        merged = [r for r in rows if r["status"] == "merged"]
        merge_rate = len(merged) / total if total else 0
        avg_days = sum(r["days_to_merge"] for r in merged if r["days_to_merge"]) / max(len(merged), 1)
        self._db.execute(
            "INSERT OR REPLACE INTO maintainer_profiles (repo_slug, merge_rate, avg_days_to_merge) "
            "VALUES (?,?,?)", (repo_slug, merge_rate, avg_days)
        )
        self._db.commit()

    def get_profile(self, repo_slug: str) -> dict:
        row = self._db.execute(
            "SELECT * FROM maintainer_profiles WHERE repo_slug=?", (repo_slug,)
        ).fetchone()
        return dict(row) if row else {"repo_slug": repo_slug, "merge_rate": 0.5, "avg_days_to_merge": 7}

    def get_weights(self) -> dict:
        row = self._db.execute("SELECT * FROM scoring_weights ORDER BY id DESC LIMIT 1").fetchone()
        if row:
            return {"impact": row["impact_w"], "novelty": row["novelty_w"],
                    "visibility": row["visibility_w"], "difficulty": row["difficulty_w"]}
        return {"impact": 0.35, "novelty": 0.30, "visibility": 0.20, "difficulty": 0.15}

    def get_resume_bullets(self) -> list:
        rows = self._db.execute(
            "SELECT repo_slug, pr_url, resume_bullet FROM pr_outcomes "
            "WHERE status='merged' AND resume_bullet != '' ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
