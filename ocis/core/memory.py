"""
OCIS Local Memory RAG — keeping track of repos, PRs, and analysis history.
"""
from __future__ import annotations
import sqlite3
import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from ocis.config import DATABASE_URL

class OCISMemory:
    def __init__(self, db_path: str = "ocis.db"):
        # Handle DATABASE_URL if it's a sqlite URL
        if db_path.startswith("sqlite:///"):
            db_path = db_path.replace("sqlite:///", "")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Table for repositories
            conn.execute("""
                CREATE TABLE IF NOT EXISTS repositories (
                    repo_slug TEXT PRIMARY KEY,
                    project_name TEXT,
                    last_scanned_at TEXT,
                    analysis_summary TEXT,
                    intelligence_synthesis TEXT
                )
            """)
            # Table for contributions (PRs)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS contributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_slug TEXT,
                    job_id TEXT,
                    branch_name TEXT,
                    pr_title TEXT,
                    pr_url TEXT,
                    recommendation_id TEXT,
                    status TEXT,
                    created_at TEXT,
                    resume_bullet TEXT,
                    FOREIGN KEY(repo_slug) REFERENCES repositories(repo_slug)
                )
            """)
            # Table for past recommendations (to ensure novelty)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS past_recommendations (
                    id TEXT PRIMARY KEY,
                    repo_slug TEXT,
                    title TEXT,
                    type TEXT,
                    created_at TEXT,
                    FOREIGN KEY(repo_slug) REFERENCES repositories(repo_slug)
                )
            """)

    def track_repo(self, repo_slug: str, project_name: str, analysis: dict, synthesis: dict):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO repositories 
                (repo_slug, project_name, last_scanned_at, analysis_summary, intelligence_synthesis)
                VALUES (?, ?, ?, ?, ?)
            """, (
                repo_slug, 
                project_name, 
                datetime.now().isoformat(),
                json.dumps(analysis),
                json.dumps(synthesis)
            ))

    def track_contribution(self, repo_slug: str, job_id: str, rec: dict, pr_result: dict):
        with sqlite3.connect(self.db_path) as conn:
            opp = rec.get("opportunity", {})
            spec = rec.get("spec", {})
            conn.execute("""
                INSERT INTO contributions 
                (repo_slug, job_id, branch_name, pr_title, pr_url, recommendation_id, status, created_at, resume_bullet)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                repo_slug,
                job_id,
                spec.get("branch_name"),
                spec.get("pr_title"),
                pr_result.get("pr_url"),
                opp.get("id"),
                "created" if pr_result.get("status") == "success" else "failed",
                datetime.now().isoformat(),
                spec.get("resume_talking_point")
            ))
            # Also track as a past recommendation
            if opp.get("id"):
                conn.execute("INSERT OR IGNORE INTO past_recommendations (id, repo_slug, title, type, created_at) VALUES (?, ?, ?, ?, ?)",
                            (opp.get("id"), repo_slug, opp.get("title"), opp.get("type"), datetime.now().isoformat()))

    def get_repo_history(self, repo_slug: str) -> dict:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            repo = conn.execute("SELECT * FROM repositories WHERE repo_slug = ?", (repo_slug,)).fetchone()
            if not repo:
                return {}
            
            contributions = conn.execute("SELECT * FROM contributions WHERE repo_slug = ?", (repo_slug,)).fetchall()
            past_recs = conn.execute("SELECT * FROM past_recommendations WHERE repo_slug = ?", (repo_slug,)).fetchall()
            
            return {
                "repo": dict(repo),
                "contributions": [dict(c) for c in contributions],
                "past_recommendations": [dict(p) for p in past_recs]
            }

    def get_all_past_recommendations(self, repo_slug: str) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT title FROM past_recommendations WHERE repo_slug = ?", (repo_slug,)).fetchall()
            return [r[0] for r in rows]

_memory: Optional[OCISMemory] = None

def get_memory() -> OCISMemory:
    global _memory
    if _memory is None:
        from ocis.config import DATABASE_URL
        _memory = OCISMemory(DATABASE_URL)
    return _memory
