"""
OCIS Orchestrator — 6-phase pipeline state machine.
Phases: GATHERING → ANALYZING → CORRELATING → RECOMMENDING → AWAITING_HITL → EXECUTING → DONE
"""
from __future__ import annotations
import uuid
import tempfile
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Dict, List, Optional, Any


class OCISJobStatus(str, Enum):
    SUBMITTED     = "submitted"
    GATHERING     = "gathering"
    ANALYZING     = "analyzing"
    CORRELATING   = "correlating"
    RECOMMENDING  = "recommending"
    AWAITING_HITL = "awaiting_hitl"
    EXECUTING     = "executing"
    DONE          = "done"
    FAILED        = "failed"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class OCISJob:
    job_id: str
    repo_url: str
    repo_slug: str
    status: OCISJobStatus = OCISJobStatus.SUBMITTED
    progress: int = 0

    intelligence: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)
    opportunities: list = field(default_factory=list)
    recommendations: list = field(default_factory=list)
    approved: list = field(default_factory=list)
    pr_results: list = field(default_factory=list)

    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    logs: list = field(default_factory=list)

    def log(self, msg: str, level: str = "INFO"):
        entry = {"ts": _now(), "level": level, "msg": msg}
        self.logs.append(entry)
        self.updated_at = _now()
        print(f"[OCIS:{self.job_id}] [{level}] {msg}")

    def set_progress(self, pct: int):
        self.progress = pct
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "repo_url": self.repo_url,
            "repo_slug": self.repo_slug,
            "status": self.status.value,
            "progress": self.progress,
            "intelligence": self.intelligence,
            "analysis": self.analysis,
            "opportunities": self.opportunities,
            "recommendations": self.recommendations,
            "approved": self.approved,
            "pr_results": self.pr_results,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "logs": self.logs,
        }


class OCISOrchestrator:
    def __init__(self):
        self._jobs: Dict[str, OCISJob] = {}
        self._lock = Lock()

    def create_job(self, repo_url: str) -> str:
        slug = _url_to_slug(repo_url)
        job_id = str(uuid.uuid4())[:10]
        job = OCISJob(job_id=job_id, repo_url=repo_url, repo_slug=slug)
        with self._lock:
            self._jobs[job_id] = job
        return job_id

    def get_job(self, job_id: str) -> Optional[OCISJob]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> List[dict]:
        return [j.to_dict() for j in self._jobs.values()]

    def approve_recommendations(self, job_id: str, approved_ids: list) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job.approved = [r for r in job.recommendations
                        if r.get("opportunity", {}).get("id") in approved_ids]
        if not job.approved:
            job.approved = job.recommendations  # approve all if none specified
        job.status = OCISJobStatus.AWAITING_HITL
        job.updated_at = _now()
        return True

    def run_pipeline(self, job_id: str):
        """Run phases 1-4 then pause for HiTL. Called in background thread."""
        job = self._jobs.get(job_id)
        if not job:
            print(f"DEBUG: Job {job_id} not found in orchestrator")
            return

        job.log("Starting autonomous pipeline...")
        tmp_root = tempfile.mkdtemp(prefix=f"ocis_{job_id}_")
        try:
            # Phase 1: Intelligence Gathering
            job.status = OCISJobStatus.GATHERING
            job.set_progress(5)
            job.log("Phase 1: Intelligence Gathering started")
            from ocis.intelligence.gatherer import IntelligenceGatherer
            gatherer = IntelligenceGatherer()
            job.intelligence = gatherer.gather(job.repo_slug, log=job.log)
            job.set_progress(25)
            job.log(f"Phase 1 complete. Project: {job.intelligence.get('project_name')}")

            # Phase 2: Repo Analysis (clone first)
            job.status = OCISJobStatus.ANALYZING
            job.log("Phase 2: Cloning repository for deep analysis...")
            repo_dir = _clone_repo(job.repo_url, tmp_root, log=job.log)
            job.log(f"Cloned to {repo_dir}")
            from ocis.analysis.repo_analyzer import RepoAnalyzer
            analyzer = RepoAnalyzer()
            job.analysis = analyzer.analyze(repo_dir, log=job.log)
            job.set_progress(50)
            job.log(f"Phase 2 complete. Files: {job.analysis.get('stats', {}).get('total_files', 0)}, "
                    f"TODOs: {job.analysis.get('stats', {}).get('todo_count', 0)}")

            # Phase 3: Correlation
            job.status = OCISJobStatus.CORRELATING
            job.log("Phase 3: Correlating intelligence with code gaps...")
            from ocis.correlation.engine import CorrelationEngine
            correlator = CorrelationEngine()
            job.opportunities = correlator.correlate(job.intelligence, job.analysis, log=job.log)
            job.set_progress(70)
            job.log(f"Phase 3 complete. Opportunities found: {len(job.opportunities)}")

            # Phase 4: Recommendation Generation
            job.status = OCISJobStatus.RECOMMENDING
            job.log("Phase 4: Generating contribution recommendations...")
            from ocis.recommendation.generator import RecommendationGenerator
            gen = RecommendationGenerator()
            job.recommendations = gen.generate(
                job.opportunities, job.intelligence, job.analysis, log=job.log
            )
            job.set_progress(90)
            job.log(f"Phase 4 complete. Recommendations: {len(job.recommendations)}")

            # Track repository in local memory
            from ocis.core.memory import get_memory
            get_memory().track_repo(
                job.repo_slug, 
                job.intelligence.get("project_name", ""),
                job.analysis,
                job.intelligence.get("synthesis", {})
            )

            # Pause for human review
            job.status = OCISJobStatus.AWAITING_HITL
            job.set_progress(95)
            job.log("Waiting for human review. Visit /ui to approve contributions.")

        except Exception as e:
            job.status = OCISJobStatus.FAILED
            job.error = str(e)
            job.log(f"Pipeline failed: {e}", "ERROR")
        finally:
            shutil.rmtree(tmp_root, ignore_errors=True)

    def run_execution(self, job_id: str):
        """Phase 6: Execute approved recommendations. Called after human approval."""
        job = self._jobs.get(job_id)
        if not job:
            return

        job.status = OCISJobStatus.EXECUTING
        job.log("Phase 6: Autonomous Execution started")

        from ocis.execution.executor import OCISExecutor
        executor = OCISExecutor()
        pr_results = []

        approved = job.approved or job.recommendations
        for i, rec in enumerate(approved):
            job.log(f"Executing recommendation {i+1}/{len(approved)}: "
                    f"{rec.get('opportunity', {}).get('title', '')[:50]}...")
            result = executor.execute(
                job_id=job_id,
                recommendation=rec,
                intelligence=job.intelligence,
                upstream_slug=job.repo_slug,
                log=job.log,
            )
            pr_results.append({
                "recommendation_title": rec.get("opportunity", {}).get("title", ""),
                **result,
            })
            
            # Track contribution in local memory
            from ocis.core.memory import get_memory
            get_memory().track_contribution(job.repo_slug, job_id, rec, result)

            job.set_progress(95 + int(5 * (i + 1) / max(len(approved), 1)))

        job.pr_results = pr_results
        job.status = OCISJobStatus.DONE
        job.set_progress(100)
        job.log(f"Phase 6 complete. PRs: {len([r for r in pr_results if r.get('success')])}/{len(pr_results)}")


def _url_to_slug(url: str) -> str:
    parts = url.rstrip("/").replace(".git", "").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1]}"
    return url


def _clone_repo(url: str, tmp_root: str, log=None) -> str:
    repo_dir = f"{tmp_root}/repo"
    if log:
        log(f"Starting shallow clone of {url} (this may take a while for large repos)...")
    r = subprocess.run(
        ["git", "clone", "--depth=1", url, repo_dir],
        capture_output=True, text=True, timeout=1200, # Increased to 20 mins
    )
    if r.returncode != 0:
        raise RuntimeError(f"Clone failed: {r.stderr[:300]}")
    return repo_dir


# Singleton
_orchestrator: Optional[OCISOrchestrator] = None


def get_orchestrator() -> OCISOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = OCISOrchestrator()
    return _orchestrator
