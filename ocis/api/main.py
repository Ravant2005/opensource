"""
OCIS FastAPI — full REST API with SSE log streaming.
"""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from threading import Thread
from typing import Optional, List

import mimetypes
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ocis.agents.orchestrator import get_orchestrator, OCISJobStatus
from ocis.config import OCIS_DRY_RUN, OPENROUTER_API_KEY, GITHUB_TOKEN, GITHUB_USERNAME

app = FastAPI(
    title="OCIS — Opensource Contributor Intelligence System",
    description="Discover, analyse, and contribute to top open-source projects autonomously.",
    version="1.0.0",
)

@app.on_event("startup")
async def validate_config():
    missing = []
    if not OPENROUTER_API_KEY:
        missing.append("OPENROUTER_API_KEY")
    if not GITHUB_TOKEN:
        missing.append("GITHUB_TOKEN")
    if not GITHUB_USERNAME:
        missing.append("GITHUB_USERNAME")
    if missing:
        import warnings
        warnings.warn(
            f"OCIS: Missing environment variables: {', '.join(missing)}. "
            f"Copy .env.example to .env and fill them in.",
            UserWarning,
            stacklevel=2,
        )
        print(f"\n⚠️  WARNING: Missing env vars: {', '.join(missing)}")
        print("   LLM calls and GitHub API calls will fail until these are set.\n")
    else:
        print(f"\n✅  OCIS ready. Dry-run mode: {OCIS_DRY_RUN}\n")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_DASHBOARD = Path(__file__).parent.parent / "dashboard"
if _DASHBOARD.exists():
    # Ensure .jsx files are served with a JavaScript MIME type so browsers and
    # babel-standalone execute/transpile them correctly.
    mimetypes.add_type("application/javascript", ".jsx")
if _DASHBOARD.exists():
    app.mount("/ui", StaticFiles(directory=str(_DASHBOARD), html=True), name="dashboard")


# ── Models ────────────────────────────────────────────────────────────────────

class JobCreateRequest(BaseModel):
    repo_url: str

class ApproveRequest(BaseModel):
    approved_ids: List[str] = []  # empty = approve all

class ExecuteRequest(BaseModel):
    pass


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
def root():
    return {
        "service": "OCIS",
        "version": "1.0.0",
        "ui": "/ui",
        "docs": "/docs",
        "status": "online",
    }

@app.get("/api/v1/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "openrouter_key": bool(OPENROUTER_API_KEY),
        "github_token": bool(GITHUB_TOKEN),
        "github_username": GITHUB_USERNAME,
        "dry_run_default": OCIS_DRY_RUN,
    }

@app.get("/api/v1/stats", tags=["Health"])
def stats():
    orch = get_orchestrator()
    jobs = orch.list_jobs()
    done = [j for j in jobs if j["status"] == OCISJobStatus.DONE.value]
    total_prs = sum(len(j.get("pr_results", [])) for j in done)
    successful_prs = sum(
        sum(1 for r in j.get("pr_results", []) if r.get("success"))
        for j in done
    )
    return {
        "total_jobs": len(jobs),
        "completed_jobs": len(done),
        "total_prs_opened": total_prs,
        "successful_prs": successful_prs,
        "recent_jobs": jobs[-5:],
    }


# ── Job lifecycle ─────────────────────────────────────────────────────────────

@app.post("/api/v1/jobs", tags=["Jobs"])
def create_job(req: JobCreateRequest, background_tasks: BackgroundTasks):
    orch = get_orchestrator()
    job_id = orch.create_job(req.repo_url)
    job = orch.get_job(job_id)
    job.log(f"Job created for {req.repo_url}")

    def _run():
        orch.run_pipeline(job_id)

    background_tasks.add_task(_run)
    return {"status": "submitted", "job_id": job_id, "repo_slug": job.repo_slug}


@app.get("/api/v1/jobs", tags=["Jobs"])
def list_jobs():
    return {"jobs": get_orchestrator().list_jobs()}


@app.get("/api/v1/jobs/{job_id}", tags=["Jobs"])
def get_job(job_id: str):
    job = get_orchestrator().get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return job.to_dict()


# ── SSE log stream ────────────────────────────────────────────────────────────

@app.get("/api/v1/jobs/{job_id}/logs", tags=["Jobs"])
async def stream_logs(job_id: str, since: int = 0):
    """Server-Sent Events stream of live job logs."""
    async def generator():
        last_idx = since
        terminal = {OCISJobStatus.DONE, OCISJobStatus.FAILED, OCISJobStatus.AWAITING_HITL}
        while True:
            job = get_orchestrator().get_job(job_id)
            if not job:
                yield f"data: {json.dumps({'error': 'job not found'})}\n\n"
                break
            new_logs = job.logs[last_idx:]
            for entry in new_logs:
                yield f"data: {json.dumps(entry)}\n\n"
                last_idx += 1
            if OCISJobStatus(job.status) in terminal:
                yield f"data: {json.dumps({'status': job.status, 'progress': job.progress})}\n\n"
                break
            await asyncio.sleep(0.5)

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Human-in-the-loop ─────────────────────────────────────────────────────────

@app.get("/api/v1/jobs/{job_id}/review", tags=["HiTL"])
def get_review(job_id: str):
    job = get_orchestrator().get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return {
        "job_id": job_id,
        "status": job.status,
        "repo_slug": job.repo_slug,
        "intelligence_summary": {
            "project_name": job.intelligence.get("project_name"),
            "synthesis": job.intelligence.get("synthesis", {}),
            "metadata": job.intelligence.get("github", {}).get("metadata", {}),
        },
        "analysis_summary": {
            "stats": job.analysis.get("stats", {}),
            "languages": job.analysis.get("languages", {}),
            "ci_analysis": job.analysis.get("ci_analysis", {}),
        },
        "opportunities": job.opportunities,
        "recommendations": job.recommendations,
    }


@app.post("/api/v1/jobs/{job_id}/approve", tags=["HiTL"])
def approve_recommendations(job_id: str, req: ApproveRequest):
    orch = get_orchestrator()
    job = orch.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    if job.status != OCISJobStatus.AWAITING_HITL:
        raise HTTPException(
            400,
            f"Job must be in 'awaiting_hitl' state to approve. Current state: {job.status}. "
            f"Wait for Phase 4 to complete."
        )
    orch.approve_recommendations(job_id, req.approved_ids)
    return {"status": "approved", "approved_count": len(job.approved)}


@app.post("/api/v1/jobs/{job_id}/execute", tags=["HiTL"])
def execute_job(job_id: str, req: ExecuteRequest, background_tasks: BackgroundTasks):
    orch = get_orchestrator()
    job = orch.get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")

    def _run():
        orch.run_execution(job_id)

    background_tasks.add_task(_run)
    return {"status": "executing", "job_id": job_id,
            "approved_count": len(job.approved or job.recommendations)}


# ── Results ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/jobs/{job_id}/results", tags=["Results"])
def get_results(job_id: str):
    job = get_orchestrator().get_job(job_id)
    if not job:
        raise HTTPException(404, f"Job {job_id} not found")
    return {
        "job_id": job_id,
        "status": job.status,
        "pr_results": job.pr_results,
        "resume_bullets": [
            r.get("resume_bullet", "") for r in job.pr_results if r.get("success")
        ],
    }


@app.get("/api/v1/resume", tags=["Jobs"])
def get_resume():
    """All successful PRs formatted as resume bullets."""
    import sqlite3
    from ocis.core.memory import get_memory
    with sqlite3.connect(get_memory().db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT resume_bullet FROM contributions WHERE status = 'created'").fetchall()
    
    bullets = [{"bullet": r["resume_bullet"]} for r in rows if r["resume_bullet"]]
    return {"resume_bullets": bullets, "markdown": "\n".join(f"- {b['bullet']}" for b in bullets)}
