"""
ASE FastAPI service.
Primary UX flow:
1) Submit GitHub URL
2) Track live analysis logs and scanner/tool readiness
3) Review vulnerabilities and improvements
4) Create PR from a generated patch in one click
"""
from __future__ import annotations
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Callable
from datetime import datetime, UTC
from threading import Lock
import uuid
import os
import re
import tempfile
import shutil
import subprocess
import time
from pathlib import Path

from ase.config import GEMINI_API_KEY, GITHUB_TOKEN
from ase.security.static.analyzer import (
    SemgrepAnalyzer,
    GitleaksAnalyzer,
    TrivyAnalyzer,
    StaticAnalysisOrchestrator,
    UnifiedFinding,
)
from ase.security.static.improvements import RepositoryImprovementAnalyzer
from ase.security.reasoning.agent import ReasoningAgent
from ase.security.behavioral.analyzer import BehavioralAnalyzer
from ase.patch.generator import PatchGenerator
from ase.patch.scorer import PatchQualityScorer
from ase.validation.runner import SandboxRunner
from ase.contribution.engine import PRContributionEngine
from ase.agents.orchestrator import AgentOrchestrator, JobStatus

app = FastAPI(
    title="Autonomous Security Engine (ASE)",
    description="Automated vulnerability detection, patch generation, and PR contribution.",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DASHBOARD = Path(__file__).parent.parent / "dashboard"
if _DASHBOARD.exists():
    app.mount("/ui", StaticFiles(directory=str(_DASHBOARD), html=True), name="dashboard")

_orchestrator = AgentOrchestrator(dry_run=True)
_ANALYSIS_JOBS: Dict[str, Dict[str, Any]] = {}
_ANALYSIS_LOCK = Lock()
_MAX_LOG_ENTRIES = 1200


class RepoAnalyzeRequest(BaseModel):
    repo_url: str
    dry_run: bool = True
    max_findings: int = 20


class PRCreateRequest(BaseModel):
    repo_url: str
    repo_slug: str
    finding: Dict[str, Any]
    patch: str
    explanation: str
    dry_run: bool = True


class BulkPRItem(BaseModel):
    finding: Dict[str, Any]
    patch: str
    explanation: str = ""


class BulkPRRequest(BaseModel):
    repo_url: str
    repo_slug: str
    patches: List[BulkPRItem]
    dry_run: bool = True


class JobSubmitRequest(BaseModel):
    repo_url: str
    repo_path: str
    repo_slug: str
    build_cmd: Optional[str] = None
    test_cmd: Optional[str] = None
    dry_run: bool = True


class ScanRequest(BaseModel):
    repo_path: str
    semgrep_config: str = "auto"


class PatchRequest(BaseModel):
    finding: Dict[str, Any]
    code_context: str
    reasoning_context: str
    original_code: Optional[str] = ""
    public_api_names: Optional[List[str]] = []


class ValidationRequest(BaseModel):
    repo_path: str
    build_cmd: Optional[str] = None
    test_cmd: Optional[str] = None


class PRRequest(BaseModel):
    repo_path: str
    repo_slug: str
    branch_name: str
    commit_msg: str
    pr_title: str
    pr_body: str
    target_branch: str = "main"
    dry_run: bool = True


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _new_job(req: RepoAnalyzeRequest) -> Dict[str, Any]:
    repo_slug = _url_to_slug(req.repo_url)
    return {
        "job_id": str(uuid.uuid4())[:10],
        "status": "queued",
        "progress": 0,
        "repo_url": req.repo_url,
        "repo_slug": repo_slug,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "logs": [],
        "result": None,
        "error": None,
        "diagnostics": _collect_system_diagnostics(),
    }


def _job_insert(job: Dict[str, Any]) -> str:
    with _ANALYSIS_LOCK:
        _ANALYSIS_JOBS[job["job_id"]] = job
    return job["job_id"]


def _job_get(job_id: str) -> Optional[Dict[str, Any]]:
    with _ANALYSIS_LOCK:
        job = _ANALYSIS_JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def _job_update(job_id: str, **fields):
    with _ANALYSIS_LOCK:
        job = _ANALYSIS_JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = _utc_now()


def _job_log(job_id: str, message: str, level: str = "INFO"):
    entry = {"ts": _utc_now(), "level": level, "message": message}
    with _ANALYSIS_LOCK:
        job = _ANALYSIS_JOBS.get(job_id)
        if not job:
            return
        logs = job.get("logs", [])
        logs.append(entry)
        if len(logs) > _MAX_LOG_ENTRIES:
            del logs[:-_MAX_LOG_ENTRIES]
        job["logs"] = logs
        job["updated_at"] = _utc_now()


def _tool_check(binary: str, version_arg: str = "--version", install_hint: str = "") -> Dict[str, Any]:
    cmd_path = _resolve_binary(binary)
    if not cmd_path:
        return {
            "name": binary,
            "available": False,
            "healthy": False,
            "path": "",
            "version": "",
            "install_hint": install_hint,
        }
    version = ""
    available = True
    healthy = True
    
    # Use a robust environment for checks
    env = os.environ.copy()
    cert_file = "/opt/homebrew/etc/ca-certificates/cert.pem"
    if os.path.exists(cert_file):
        env.setdefault("SSL_CERT_FILE", cert_file)
        env.setdefault("X509_CERT_FILE", cert_file)
    
    try:
        res = subprocess.run(
            [cmd_path, version_arg],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=env,
        )
        if res.returncode != 0:
            healthy = False
        first_line = (res.stdout or res.stderr or "").splitlines()
        if first_line:
            version = first_line[0][:180]
    except Exception:
        healthy = False
        version = "version check failed"
    return {
        "name": binary,
        "available": available,
        "healthy": healthy,
        "path": cmd_path,
        "version": version,
        "install_hint": install_hint,
    }


def _resolve_binary(name: str) -> str:
    """
    Resolve tool binaries with preference for Homebrew installs.
    """
    env_override = os.environ.get(f"ASE_{name.upper()}_BIN", "")
    if env_override and os.path.exists(env_override):
        return env_override
    preferred = f"/opt/homebrew/bin/{name}"
    if os.path.exists(preferred):
        return preferred
    return shutil.which(name) or ""


def _collect_system_diagnostics() -> Dict[str, Any]:
    tools = [
        _tool_check("brew", "--version", "Install Homebrew"),
        _tool_check("git", "--version", "Install Git"),
        _tool_check("semgrep", "--version", "brew install semgrep"),
        _tool_check("gitleaks", "version", "brew install gitleaks"),
        _tool_check("trivy", "--version", "brew install trivy"),
        _tool_check("codeql", "version", "Install CodeQL CLI from GitHub releases"),
        _tool_check("docker", "--version", "Install Docker Desktop"),
    ]
    tokens = {
        "GEMINI_API_KEY": bool(GEMINI_API_KEY or os.environ.get("GEMINI_API_KEY")),
        "GITHUB_TOKEN": bool(GITHUB_TOKEN or os.environ.get("GITHUB_TOKEN")),
    }
    recommended = []
    for tool in tools:
        if not tool["available"] and tool.get("install_hint"):
            recommended.append(tool["install_hint"])
        elif tool["available"] and not tool.get("healthy", True):
            if tool["name"] == "semgrep":
                recommended.append("Semgrep runtime check failed. ASE will use local fallback rules when auto registry is unreachable.")
            else:
                recommended.append(f"{tool['name']} is installed but failed runtime check.")
    if not tokens["GEMINI_API_KEY"]:
        recommended.append("Set GEMINI_API_KEY in .env")
    if not tokens["GITHUB_TOKEN"]:
        recommended.append("Set GITHUB_TOKEN in .env")
    macos_setup_steps = _collect_macos_setup_steps(tools, tokens)
    return {
        "tools": tools,
        "tokens": tokens,
        "recommended_actions": recommended,
        "macos_setup_steps": macos_setup_steps,
    }


def _collect_macos_setup_steps(tools: List[Dict[str, Any]], tokens: Dict[str, bool]) -> List[Dict[str, str]]:
    """
    Build macOS-first setup commands for one-click copy in the UI.
    """
    tool_map = {t["name"]: t for t in tools}
    steps: List[Dict[str, str]] = []
    env_file = str((Path(__file__).resolve().parents[2] / ".env"))

    def add_step(step_id: str, title: str, command: str, reason: str):
        steps.append({
            "id": step_id,
            "title": title,
            "command": command,
            "reason": reason,
        })

    if not tool_map.get("brew", {}).get("available", False):
        add_step(
            "install-homebrew",
            "Install Homebrew",
            '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"',
            "Required package manager for macOS setup.",
        )

    formula_tools = ["git", "semgrep", "gitleaks", "trivy"]
    missing_formula = [name for name in formula_tools if not tool_map.get(name, {}).get("available", False)]
    if missing_formula:
        add_step(
            "install-formula-tools",
            "Install CLI Security Tools",
            f"brew install {' '.join(missing_formula)}",
            "Installs missing analysis binaries used by ASE.",
        )

    cask_tools = ["codeql", "docker"]
    missing_casks = [name for name in cask_tools if not tool_map.get(name, {}).get("available", False)]
    if missing_casks:
        add_step(
            "install-cask-tools",
            "Install Cask Tools",
            f"brew install --cask {' '.join(missing_casks)}",
            "Installs GUI/packaged tools needed for advanced analysis and sandboxing.",
        )

    semgrep = tool_map.get("semgrep", {})
    if semgrep.get("available", False) and not semgrep.get("healthy", True):
        add_step(
            "fix-semgrep-runtime",
            "Fix Semgrep Runtime Cert Path",
            "echo 'export SSL_CERT_FILE=/opt/homebrew/etc/ca-certificates/cert.pem' >> ~/.zshrc && "
            "echo 'export X509_CERT_FILE=/opt/homebrew/etc/ca-certificates/cert.pem' >> ~/.zshrc && source ~/.zshrc",
            "Resolves common macOS certificate path issues for Semgrep.",
        )

    if not tokens.get("GEMINI_API_KEY", False):
        add_step(
            "set-gemini-key",
            "Set GEMINI API Key",
            f"printf '\\nGEMINI_API_KEY=YOUR_GEMINI_API_KEY\\n' >> {env_file}",
            "Enables stronger AI security reasoning and patch generation.",
        )

    if not tokens.get("GITHUB_TOKEN", False):
        add_step(
            "set-github-token",
            "Set GitHub Token",
            f"printf '\\nGITHUB_TOKEN=YOUR_GITHUB_TOKEN\\n' >> {env_file}",
            "Enables real PR creation and GitHub API operations.",
        )

    add_step(
        "verify-toolchain",
        "Verify Toolchain",
        "git --version && semgrep --version && gitleaks version && trivy --version && codeql version",
        "Quick readiness check before running large repository scans.",
    )
    add_step(
        "run-ase",
        "Run ASE on macOS",
        "cd /Users/benny/Documents/opensource_contri && ASE_RELOAD=false python3 ase/run.py",
        "Starts the ASE API and UI locally at http://127.0.0.1:8001/ui",
    )
    return steps


def _execute_analysis(
    req: RepoAnalyzeRequest,
    log: Optional[Callable[[str, str], None]] = None,
    progress: Optional[Callable[[int], None]] = None,
) -> Dict[str, Any]:
    def emit(msg: str, level: str = "INFO"):
        if log:
            log(msg, level)

    def set_progress(val: int):
        if progress:
            progress(val)

    tmp_root = tempfile.mkdtemp(prefix="ase_analyze_")
    repo_dir = Path(tmp_root) / "repo"
    try:
        set_progress(5)
        emit(f"Cloning repository: {req.repo_url}")
        _clone_repo(req.repo_url, str(repo_dir))
        repo_slug = _url_to_slug(req.repo_url)
        emit(f"Repository cloned to temporary workspace: {repo_slug}")

        diagnostics = _collect_system_diagnostics()
        missing = [t["name"] for t in diagnostics["tools"] if not t["available"]]
        if missing:
            emit(f"Missing tools detected: {', '.join(missing)}", "WARN")
        if not diagnostics["tokens"]["GEMINI_API_KEY"]:
            emit("GEMINI_API_KEY missing. AI reasoning will use fallback mode.", "WARN")
        if not diagnostics["tokens"]["GITHUB_TOKEN"]:
            emit("GITHUB_TOKEN missing. PR creation will work only in dry-run mode.", "WARN")

        set_progress(14)
        emit("Running static scanners...")
        static_findings = _run_static_scans(str(repo_dir), emit)
        static_findings = [f for f in static_findings if f.severity in ("CRITICAL", "ERROR") or f.exploitability_score > 0.8]
        findings = [f.to_dict() for f in static_findings[:req.max_findings]]
        emit(f"Static analysis complete. Findings: {len(findings)}")

        set_progress(40)
        emit("Running behavioral analysis...")
        behavioral = BehavioralAnalyzer()
        behavioral_findings = [b.to_dict() for b in behavioral.analyze_repo(str(repo_dir))]
        behavioral_findings = [b for b in behavioral_findings if b.get("severity") in ("CRITICAL", "ERROR")]
        emit(f"Behavioral analysis complete. Findings: {len(behavioral_findings)}")

        set_progress(56)
        emit("Running repository improvement analysis...")
        improver = RepositoryImprovementAnalyzer()
        improvements = [i.to_dict() for i in improver.analyze_repo(str(repo_dir))]
        improvements = [i for i in improvements if i.get("severity") in ("HIGH", "CRITICAL")]
        emit(f"Improvement analysis complete. Suggestions: {len(improvements)}")

        set_progress(70)
        emit("Running AI reasoning on top findings...")
        reasoner = ReasoningAgent()
        assessments = []
        for idx, finding in enumerate(static_findings[:5], start=1):
            emit(f"Reasoning {idx}/5 for rule {finding.rule_id}...")
            assessed = reasoner.analyze_finding(finding.to_dict(), str(repo_dir))
            assessed["finding"] = finding.to_dict()
            assessments.append(assessed)
        emit(f"AI reasoning complete. Assessed: {len(assessments)}")

        set_progress(84)
        emit("Generating and scoring patch proposals...")
        generator = PatchGenerator()
        scorer = PatchQualityScorer()
        patches = []
        for a in assessments:
            if a.get("is_false_positive"):
                continue
            finding = a["finding"]
            snippet = reasoner.extract_ast_snippet(
                str(repo_dir),
                finding.get("file_path", ""),
                int(finding.get("line_number", 1)),
                context_window=12,
            )
            patch_result = generator.generate_patch(
                finding=finding,
                code_context=snippet,
                reasoning_context=a.get("exploit_scenario", ""),
            )
            patch_str = patch_result.get("patch", "")
            original_code = _safe_read_text(repo_dir / finding.get("file_path", ""))
            quality = scorer.score(
                patch_str=patch_str,
                original_code=original_code,
                patched_code=original_code or "pass\n",
            )
            patches.append({
                "finding": finding,
                "patch": patch_str,
                "explanation": patch_result.get("explanation", ""),
                "quality": quality,
                "ready_for_pr": quality.get("passes_threshold", False),
            })
        emit(f"Patch generation complete. Candidates: {len(patches)}")
        set_progress(100)
        emit("Analysis pipeline completed successfully.")

        return {
            "status": "success",
            "repo_url": req.repo_url,
            "repo_slug": repo_slug,
            "diagnostics": diagnostics,
            "summary": {
                "static_findings": len(findings),
                "behavioral_findings": len(behavioral_findings),
                "improvements": len(improvements),
                "ai_assessed": len(assessments),
                "patches_generated": len(patches),
                "patches_ready": sum(1 for p in patches if p["ready_for_pr"]),
            },
            "findings": findings,
            "behavioral_findings": behavioral_findings,
            "improvements": improvements,
            "assessments": assessments,
            "patches": patches,
        }
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _run_static_scans(repo_path: str, emit: Callable[[str, str], None]) -> List[UnifiedFinding]:
    all_findings: List[UnifiedFinding] = []

    semgrep_bin = _resolve_binary("semgrep")
    gitleaks_bin = _resolve_binary("gitleaks")
    trivy_bin = _resolve_binary("trivy")
    codeql_bin = _resolve_binary("codeql")
    semgrep_available = bool(semgrep_bin)
    gitleaks_available = bool(gitleaks_bin)
    trivy_available = bool(trivy_bin)
    codeql_available = bool(codeql_bin)
    if semgrep_available:
        start = time.time()
        # We always try real Semgrep if binary is found. 
        # Fallback to local rules is handled internally by the analyzer only if CLI fails.
        semgrep_results = SemgrepAnalyzer(semgrep_bin=semgrep_bin).scan(repo_path, config_path="auto")
        emit(f"Semgrep completed in {time.time() - start:.1f}s with {len(semgrep_results)} findings.")
        all_findings.extend(semgrep_results)
    else:
        emit("Semgrep not installed. Using local static fallback rules for basic coverage.", "WARN")
        fallback = _local_static_fallback_scan(repo_path)
        emit(f"Local fallback static scan produced {len(fallback)} findings.")
        all_findings.extend(fallback)

    if gitleaks_available:
        start = time.time()
        gitleaks_results = GitleaksAnalyzer(gitleaks_bin=gitleaks_bin).scan(repo_path)
        emit(f"Gitleaks completed in {time.time() - start:.1f}s with {len(gitleaks_results)} findings.")
        all_findings.extend(gitleaks_results)
    else:
        emit("Gitleaks not installed. Secret scanning skipped.", "WARN")

    if trivy_available:
        start = time.time()
        trivy_results = TrivyAnalyzer(trivy_bin=trivy_bin).scan(repo_path)
        emit(f"Trivy completed in {time.time() - start:.1f}s with {len(trivy_results)} findings.")
        all_findings.extend(trivy_results)
    else:
        emit("Trivy not installed. Dependency CVE scanning skipped.", "WARN")

    if codeql_available:
        emit("CodeQL CLI detected. Full CodeQL pipeline not yet enabled in this endpoint (query pack path required).", "WARN")
    else:
        emit("CodeQL not installed.", "WARN")

    seen = set()
    deduped: List[UnifiedFinding] = []
    for finding in all_findings:
        if finding.dedup_key in seen:
            continue
        seen.add(finding.dedup_key)
        deduped.append(finding)
    deduped.sort(key=lambda f: f.exploitability_score, reverse=True)
    return deduped


def _local_static_fallback_scan(repo_path: str) -> List[UnifiedFinding]:
    findings: List[UnifiedFinding] = []
    patterns = [
        ("ase.fallback.python.os-system", r"\bos\.system\s*\(", "Potential OS command injection", "ERROR", ["CWE-78"]),
        ("ase.fallback.python.eval", r"\beval\s*\(", "Dynamic eval detected", "WARNING", ["CWE-94"]),
        ("ase.fallback.python.exec", r"\bexec\s*\(", "Dynamic exec detected", "WARNING", ["CWE-94"]),
        ("ase.fallback.js.eval", r"\beval\s*\(", "Dynamic eval detected", "WARNING", ["CWE-94"]),
        ("ase.fallback.secret.aws", r"(AKIA|ASIA)[A-Z0-9]{16}", "Possible AWS access key", "ERROR", ["CWE-312"]),
    ]
    allowed = {".py", ".js", ".ts", ".go", ".java", ".c", ".cpp", ".rs"}
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv"}]
        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in allowed:
                continue
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, repo_path)
            try:
                content = open(fpath, encoding="utf-8", errors="ignore").read()
            except IOError:
                continue
            for rule_id, regex, message, severity, cwe in patterns:
                for m in re.finditer(regex, content):
                    line = content[:m.start()].count("\n") + 1
                    snippet = content.splitlines()[line - 1][:180] if content.splitlines() else ""
                    findings.append(
                        UnifiedFinding(
                            tool="ase-fallback",
                            rule_id=rule_id,
                            file_path=rel,
                            line_number=line,
                            message=message,
                            severity=severity,
                            cwe=cwe,
                            snippet=snippet,
                        )
                    )
    return findings


def _run_analysis_job(job_id: str, req_data: Dict[str, Any]):
    req = RepoAnalyzeRequest(**req_data)
    _job_update(job_id, status="running", progress=1)
    _job_log(job_id, f"Job started for {req.repo_url}")
    try:
        result = _execute_analysis(
            req,
            log=lambda msg, level="INFO": _job_log(job_id, msg, level),
            progress=lambda p: _job_update(job_id, progress=p),
        )
        _job_update(job_id, status="completed", progress=100, result=result)
        _job_log(job_id, "Job completed successfully.")
    except Exception as e:
        _job_update(job_id, status="failed", error=str(e))
        _job_log(job_id, f"Job failed: {e}", "ERROR")


@app.get("/", tags=["Health"])
def root():
    return {"status": "online", "version": "5.0.0", "ui": "/ui"}


@app.get("/ui", tags=["UI"])
def serve_ui():
    ui_path = _DASHBOARD / "index.html"
    if ui_path.exists():
        return FileResponse(str(ui_path))
    raise HTTPException(status_code=404, detail="UI not built yet.")


@app.get("/api/v1/system/diagnostics", tags=["System"])
def system_diagnostics():
    return {"status": "success", "diagnostics": _collect_system_diagnostics()}


@app.post("/api/v1/analyze-repo/submit", tags=["Analysis"])
def submit_repo_analysis(req: RepoAnalyzeRequest, background_tasks: BackgroundTasks):
    job = _new_job(req)
    job_id = _job_insert(job)
    _job_log(job_id, "Job queued.")
    background_tasks.add_task(_run_analysis_job, job_id, req.model_dump())
    return {"status": "submitted", "job_id": job_id, "repo_slug": job["repo_slug"]}


@app.get("/api/v1/analyze-repo/jobs/{job_id}", tags=["Analysis"])
def get_repo_analysis_job(job_id: str):
    job = _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Analysis job '{job_id}' not found.")
    return job


@app.post("/api/v1/analyze-repo", tags=["Analysis"])
def analyze_repo(req: RepoAnalyzeRequest):
    """
    Synchronous analysis endpoint.
    UI should prefer `/api/v1/analyze-repo/submit` + polling for live logs.
    """
    try:
        return _execute_analysis(req)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/create-pr", tags=["Contribution"])
def create_pr_from_analysis(req: PRCreateRequest):
    """
    One-click PR creation:
    clone target repo, apply generated diff, commit, and open PR (dry-run by default).
    """
    repo_slug = req.repo_slug or _url_to_slug(req.repo_url)
    cwe = "_".join(req.finding.get("cwe", ["unknown"]))
    import hashlib

    short = hashlib.sha256(req.patch.encode()).hexdigest()[:6]
    branch = f"ase/fix/{cwe}-{short}"

    tmp_root = tempfile.mkdtemp(prefix="ase_pr_")
    repo_dir = Path(tmp_root) / "repo"
    try:
        _clone_repo(req.repo_url, str(repo_dir))
        _configure_local_git_identity(str(repo_dir))
        _apply_patch(repo_path=str(repo_dir), patch=req.patch)

        engine = PRContributionEngine()
        result = engine.create_pull_request(
            repo_path=str(repo_dir),
            repo_slug=repo_slug,
            branch_name=branch,
            commit_msg=f"security: fix {cwe} detected by ASE",
            pr_title=f"[ASE] Security fix: {req.finding.get('message', '')[:70]}",
            pr_body=_build_pr_body(req.finding, req.explanation),
            dry_run=req.dry_run,
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


@app.post("/api/v1/create-pr-bulk", tags=["Contribution"])
def create_pr_bulk(req: BulkPRRequest):
    """
    Apply multiple patches to the same repo in a single branch/commit,
    then open one pull request. Each patch targets a different file (or file section).
    """
    repo_slug = req.repo_slug or _url_to_slug(req.repo_url)
    if not req.patches:
        raise HTTPException(status_code=400, detail="No patches supplied.")

    import hashlib, datetime
    all_cwes = set()
    all_rules = set()
    for p in req.patches:
        f = p.finding or {}
        all_cwes.update(f.get("cwe", []))
        rid = f.get("rule_id", "")
        if rid:
            all_rules.add(rid)

    cwe_tag = hashlib.md5("".join(sorted(all_cwes)).encode()).hexdigest()[:6]
    rule_tag = hashlib.md5("".join(sorted(all_rules)).encode()).hexdigest()[:6]
    branch = f"ase/bulk/{cwe_tag}-{rule_tag}"

    commit_lines = [f"A bulk security fix from ASE covering {len(req.patches)} finding(s)."]
    for p in req.patches:
        f = p.finding or {}
        commit_lines.append(
            f"- [{f.get('severity', '?')}] {f.get('rule_id', '?')} in {f.get('file_path', '?')}: "
            f"{f.get('message', '?')[:80]}"
        )

    commit_msg = "\n".join(commit_lines)
    rule_slug = "".join(sorted(all_rules))[:60].replace(" ", "-")
    pr_title = f"[ASE] Bulk security fix: {rule_slug}"

    now = datetime.datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    pr_body_parts = [
        f"Bulk security and improvement contributions applied by ASE on {now}.",
        "",
        "### Changes",
    ]
    for p in req.patches:
        f = p.finding or {}
        pr_body_parts.append(
            f"- **{f.get('rule_id', '?')}** in `{f.get('file_path', '?')}:{f.get('line_number', '?')}` "
            f"(CWE: {', '.join(f.get('cwe', ['—']))})\n"
            f"  {p.explanation or f.get('message', '')}"
        )
    pr_body = "\n".join(pr_body_parts)

    tmp_root = tempfile.mkdtemp(prefix="ase_bulk_")
    repo_dir = Path(tmp_root) / "repo"
    try:
        _clone_repo(req.repo_url, str(repo_dir))
        _configure_local_git_identity(str(repo_dir))

        apply_result = _apply_multiple_patches(str(repo_dir), [p.model_dump() for p in req.patches])
        failed = [r for r in apply_result["results"] if not r["applied"]]
        if not apply_result["results"] or all(not r["applied"] for r in apply_result["results"]):
            # All patches failed — report it
            sample_errs = "; ".join(r["error"] for r in apply_result["results"][:3])
            raise HTTPException(status_code=400, detail=f"No patches applied. Errors: {sample_errs}")

        engine = PRContributionEngine()
        result = engine.create_pull_request(
            repo_path=str(repo_dir),
            repo_slug=repo_slug,
            branch_name=branch,
            commit_msg=commit_msg,
            pr_title=pr_title,
            pr_body=pr_body,
            dry_run=req.dry_run,
        )
        result["failed_applications"] = len(failed)
        result["total_patches"] = len(req.patches)
        result["successful_applications"] = len(apply_result["results"]) - len(failed)
        result["applied_results"] = [{"finding": r["finding"].get("rule_id", "?"), "applied": r["applied"], "error": r["error"]} for r in apply_result["results"]]
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


@app.post("/api/v1/scan", tags=["Analysis"])
def scan_repository(req: ScanRequest):
    orch = StaticAnalysisOrchestrator()
    findings = orch.run(req.repo_path, semgrep_config=req.semgrep_config)
    return {"status": "success", "count": len(findings), "findings": [f.to_dict() for f in findings]}


@app.post("/api/v1/patch", tags=["Patch"])
def generate_patch(req: PatchRequest):
    generator = PatchGenerator()
    return generator.generate_patch(req.finding, req.code_context, req.reasoning_context)


@app.post("/api/v1/patch/score", tags=["Patch"])
def score_patch(req: PatchRequest):
    scorer = PatchQualityScorer()
    return scorer.score(
        patch_str=req.code_context,
        original_code=req.original_code or "",
        patched_code=req.reasoning_context,
        public_api_names=req.public_api_names or [],
    )


@app.post("/api/v1/validate", tags=["Validation"])
def validate_patch(req: ValidationRequest):
    runner = SandboxRunner()
    return runner.run_validation(req.repo_path, req.build_cmd, req.test_cmd)


@app.post("/api/v1/contribute", tags=["Contribution"])
def open_pull_request(req: PRRequest):
    engine = PRContributionEngine()
    return engine.create_pull_request(
        repo_path=req.repo_path,
        repo_slug=req.repo_slug,
        branch_name=req.branch_name,
        commit_msg=req.commit_msg,
        pr_title=req.pr_title,
        pr_body=req.pr_body,
        target_branch=req.target_branch,
        dry_run=req.dry_run,
    )


@app.post("/api/v1/jobs/submit", tags=["Orchestration"])
def submit_job(req: JobSubmitRequest, background_tasks: BackgroundTasks):
    _orchestrator.dry_run = req.dry_run
    job_id = _orchestrator.submit(req.repo_url, req.repo_path, req.repo_slug)
    background_tasks.add_task(_orchestrator.run_full_pipeline, job_id, req.build_cmd, req.test_cmd)
    return {"status": "submitted", "job_id": job_id}


@app.get("/api/v1/jobs/{job_id}", tags=["Orchestration"])
def get_job_status(job_id: str):
    job = _orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job.to_dict()


@app.get("/api/v1/jobs", tags=["Orchestration"])
def list_jobs():
    return {"jobs": _orchestrator.list_jobs()}


@app.get("/api/v1/prs/pending", tags=["Contribution"])
def get_pending_prs():
    pending = [j for j in _orchestrator.list_jobs() if j.get("pr_results") and j.get("status") == JobStatus.DONE.value]
    return {"pending_prs": pending}


@app.get("/api/v1/jobs/{job_id}/org-intelligence")
async def get_org_intelligence(job_id: str):
    """Return the org analysis data for a job."""
    job = _orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    org_intel = next(
        (f["data"] for f in job.findings if f.get("type") == "org_intelligence"), {}
    )
    return {"job_id": job_id, "org_intelligence": org_intel}


@app.get("/api/v1/jobs/{job_id}/feature-recommendations")
async def get_feature_recommendations(job_id: str):
    """Return feature recommendations generated for a job."""
    job = _orchestrator.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    recs = [
        a["data"] for a in job.assessments
        if a.get("type") == "feature_recommendation"
    ]
    return {"job_id": job_id, "recommendations": recs, "count": len(recs)}


@app.post("/api/v1/analyze-repo-quick")
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


def _clone_repo(repo_url: str, target_dir: str):
    clone_result = subprocess.run(
        ["git", "clone", "--depth=1", repo_url, target_dir],
        capture_output=True,
        text=True,
        timeout=240,
    )
    if clone_result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Clone failed: {clone_result.stderr[:300]}")


def _apply_patch(repo_path: str, patch: str):
    check = subprocess.run(
        ["git", "apply", "--allow-empty", "--check", "-"],
        input=patch,
        text=True,
        cwd=repo_path,
        capture_output=True,
    )
    if check.returncode != 0:
        target_rel = ""
        for line in patch.splitlines():
            if line.startswith("+++ b/"):
                target_rel = line.replace("+++ b/", "", 1).strip()
                break
        if target_rel:
            target_abs = Path(repo_path) / target_rel
            if PatchGenerator.apply_patch(str(target_abs), patch):
                return
        raise HTTPException(status_code=400, detail=f"Patch does not apply cleanly: {check.stderr[:400]}")

    apply_result = subprocess.run(
        ["git", "apply", "--allow-empty", "-"],
        input=patch,
        text=True,
        cwd=repo_path,
        capture_output=True,
    )
    if apply_result.returncode != 0:
        raise HTTPException(status_code=400, detail=f"Patch apply failed: {apply_result.stderr[:400]}")


def _configure_local_git_identity(repo_path: str):
    subprocess.run(["git", "config", "user.email", "ase-bot@example.com"], cwd=repo_path, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "ASE Bot"], cwd=repo_path, capture_output=True, text=True)


def _safe_read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _url_to_slug(url: str) -> str:
    parts = url.rstrip("/").split("/")
    if len(parts) >= 2:
        return f"{parts[-2]}/{parts[-1].replace('.git', '')}"
    return url


def _apply_multiple_patches(repo_path: str, patches: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Apply N patches sequentially to a cloned repo. Returns per-file results.
    Each patch is applied individually; failures for one file do not stop the rest.
    """
    results = []
    for p in patches:
        patch_str = p.get("patch", "")
        finding = p.get("finding", {})
        file_path = finding.get("file_path", "")
        ok = False
        err = ""
        try:
            # Determine which file this patch targets
            target_rel = ""
            for line in patch_str.splitlines():
                if line.startswith("+++ b/"):
                    target_rel = line.replace("+++ b/", "", 1).strip()
                    break
                if line.startswith("+++"):
                    target_rel = line.replace("+++", "", 1).strip()
                    break

            target_abs = str(Path(repo_path) / target_rel) if target_rel else str(Path(repo_path) / file_path)

            # Try git apply first
            check = subprocess.run(
                ["git", "apply", "--allow-empty", "--check", "-"],
                input=patch_str,
                text=True,
                cwd=repo_path,
                capture_output=True,
            )
            if check.returncode == 0:
                apply_result = subprocess.run(
                    ["git", "apply", "--allow-empty", "-"],
                    input=patch_str,
                    text=True,
                    cwd=repo_path,
                    capture_output=True,
                )
                ok = apply_result.returncode == 0
                if not ok:
                    err = apply_result.stderr[:300]
            else:
                # Fallback: single-file hunk applier
                if Path(target_abs).exists() and PatchGenerator.apply_patch(target_abs, patch_str):
                    ok = True
                else:
                    err = check.stderr[:300]
        except Exception as e:
            err = str(e)[:300]

        results.append({
            "finding": finding,
            "patch": patch_str,
            "applied": ok,
            "error": err,
        })
    return {"results": results}


def _build_pr_body(finding: Dict[str, Any], explanation: str) -> str:
    cwe = ", ".join(finding.get("cwe", []))
    return f"""## Security Fix - Automated by ASE

**Summary:** {finding.get('message', '')[:120]}

**Root Cause:** {cwe} detected at `{finding.get('file_path', '')}:{finding.get('line_number', '')}` by `{finding.get('tool', '')}`.

**Fix Approach:**
{explanation}

**Severity:** {finding.get('severity', '')} | **Exploitability Score:** {finding.get('exploitability_score', '')}

**References:** {cwe}

---
*This PR was generated by ASE. Please review before merging.*
"""
