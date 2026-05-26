"""
AgentOrchestrator — Master Coordinator
Coordinates the FULL pipeline:
Recon → Org Intelligence → Vulnerability Analysis → CVE Enrichment
→ Feature Recommendation → Patch/Feature Generation → Sandbox Execution
→ Validate → Contribute (fork PR)
"""
from __future__ import annotations
import os
import uuid
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum


class JobStatus(str, Enum):
    SUBMITTED = "submitted"
    INGESTING = "ingesting"
    ANALYZING = "analyzing"
    PATCHING = "patching"
    VALIDATING = "validating"
    CONTRIBUTING = "contributing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ASEJob:
    job_id: str
    repo_url: str
    repo_path: str
    repo_slug: str
    status: JobStatus = JobStatus.SUBMITTED
    progress: int = 0
    logs: List[Dict] = field(default_factory=list)
    findings: List[Dict] = field(default_factory=list)
    assessments: List[Dict] = field(default_factory=list)
    patches: List[Dict] = field(default_factory=list)
    validation_reports: List[Dict] = field(default_factory=list)
    pr_results: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


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

    def _add_log(self, job: ASEJob, level: str, message: str):
        job.logs.append({
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "message": message
        })
        job.updated_at = datetime.utcnow().isoformat()

    # ---------- Phase: Org Intelligence ----------
    def run_phase_org_intelligence(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        self._add_log(job, "INFO", "Agent starting Org Intelligence gathering...")
        try:
            from ase.intelligence.org_analyzer import OrgAnalyzer
            analyzer = OrgAnalyzer(github_token=self.github_token)
            org_intel = analyzer.full_analysis(job.repo_slug)
            job.findings.append({"type": "org_intelligence", "data": org_intel})
            self._add_log(job, "SUCCESS", f"Intelligence gathered: {org_intel.get('summary', {}).get('primary_language')} ecosystem detected.")
        except Exception as e:
            self._add_log(job, "WARNING", f"Org intelligence partial failure: {e}")
        return True

    # ---------- Phase: Static Analysis ----------
    def run_phase_analyze(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        job.status = JobStatus.ANALYZING
        self._add_log(job, "INFO", "Agent running deep static analysis...")
        try:
            from ase.security.static.analyzer import StaticAnalysisOrchestrator
            orchestrator = StaticAnalysisOrchestrator()
            raw_findings = orchestrator.run(job.repo_path)
            findings_dicts = [f.to_dict() for f in raw_findings]
            self._add_log(job, "SUCCESS", f"Analysis complete: {len(findings_dicts)} security signals detected.")
            
            # CVE enrichment
            self._add_log(job, "INFO", "Enriching signals with CVE/NVD intelligence...")
            try:
                from ase.security.vuln_database import VulnDatabase
                vdb = VulnDatabase()
                findings_dicts = vdb.bulk_enrich(findings_dicts)
            except Exception: pass

            org_intel_findings = [f for f in job.findings if f.get("type") == "org_intelligence"]
            job.findings = org_intel_findings + findings_dicts
        except Exception as e:
            job.error = str(e); job.status = JobStatus.FAILED
            self._add_log(job, "ERROR", f"Analysis failed: {e}")
            return False
        return True

    # ---------- Phase: LLM Reasoning ----------
    def run_phase_reason(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        self._add_log(job, "INFO", "Agent reasoning about detected signals...")
        vuln_findings = [f for f in job.findings if f.get("type") != "org_intelligence"]
        if not vuln_findings: return True
        try:
            from ase.security.reasoning.agent import ReasoningAgent
            agent = ReasoningAgent()
            assessments = []
            critical = [f for f in vuln_findings if f.get("severity") in ("CRITICAL", "ERROR")]
            for finding in critical[:5]:
                assessment = agent.analyze_finding(finding, job.repo_path)
                assessment["finding"] = finding
                assessments.append(assessment)
            job.assessments = assessments
            self._add_log(job, "SUCCESS", f"Reasoning complete: {len(assessments)} findings prioritized for coding.")
        except Exception as e:
            self._add_log(job, "WARNING", f"Reasoning agent encountered an issue: {e}")
        return True

    # ---------- Phase: Feature Recommendations ----------
    def run_phase_feature_recommendations(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        self._add_log(job, "INFO", "Agent identifying strategic upgrade opportunities...")
        try:
            from ase.intelligence.feature_recommender import FeatureRecommender
            org_intel_entry = next((f["data"] for f in job.findings if f.get("type") == "org_intelligence"), {})
            recommender = FeatureRecommender()
            vuln_findings = [f for f in job.findings if f.get("type") != "org_intelligence"]
            recs = recommender.generate_recommendations(org_intel_entry, vuln_findings, 3)
            for rec in recs:
                job.assessments.append({"type": "feature_recommendation", "data": rec})
            self._add_log(job, "SUCCESS", f"Strategic planning complete: {len(recs)} feature upgrades proposed.")
        except Exception as e:
            self._add_log(job, "WARNING", f"Feature recommender issue: {e}")
        return True

    # ---------- Phase: Patch + Feature Code Generation ----------
    def run_phase_patch(self, job_id: str) -> bool:
        import os as _os
        job = self._jobs.get(job_id)
        if not job: return False
        job.status = JobStatus.PATCHING
        self._add_log(job, "INFO", "Agent preparing isolated sandbox for code generation...")

        # Create sandbox
        try:
            from ase.sandbox.executor import SandboxExecutor
            sandbox = SandboxExecutor()
            sandbox_path = sandbox.create_sandbox(job.repo_path, job.job_id)
            job.repo_path = sandbox_path
            self._add_log(job, "SUCCESS", "Isolated sandbox ready. Commencing AI coding session...")
        except Exception as e:
            self._add_log(job, "WARNING", f"Sandbox creation failed, using direct path: {e}")
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
            for i, assessment in enumerate(security_assessments):
                finding = assessment.get("finding", {})
                self._add_log(job, "INFO", f"Agent coding security fix {i+1}/{len(security_assessments)}: {finding.get('rule_id')}...")
                
                patch_result = generator.generate_patch(
                    finding,
                    code_context=assessment.get("reasoning", "")[:500],
                    reasoning_context=assessment.get("exploit_scenario", ""),
                )
                
                if patch_result.get("status") == "success":
                    patch_str = patch_result.get("patch", "")
                    quality = scorer.score(patch_str, "", patch_str)
                    patch_result["quality"] = quality
                    patch_result["finding"] = finding
                    patch_result["patch_type"] = "security_fix"

                    if quality.get("passes_threshold", False) and patch_str:
                        target_rel = finding.get("file_path", "")
                        target_abs = _os.path.join(sandbox_path, target_rel)
                        if _os.path.exists(target_abs):
                            applied = PatchGenerator.apply_patch(target_abs, patch_str)
                            patch_result["applied_to_disk"] = applied
                            if applied:
                                self._add_log(job, "SUCCESS", f"Security fix applied successfully to {target_rel}.")
                        patches.append(patch_result)
                else:
                    self._add_log(job, "WARNING", f"Agent could not generate a safe fix for {finding.get('rule_id')}.")

            # 2. Feature patches
            feature_assessments = [a for a in job.assessments if a.get("type") == "feature_recommendation"]
            for i, feat_assessment in enumerate(feature_assessments):
                rec = feat_assessment.get("data", {})
                self._add_log(job, "INFO", f"Agent implementing strategic upgrade {i+1}/{len(feature_assessments)}: {rec.get('title')}...")
                
                try:
                    repo_struct = "" # Simplified for brevity
                    feat_patch = recommender.generate_feature_patch(rec, repo_struct)
                    if feat_patch.get("status") == "success":
                        feat_patch["patch_type"] = "feature_addition"
                        feat_patch["recommendation"] = rec
                        self._add_log(job, "SUCCESS", f"Strategic upgrade implemented: {rec.get('title')}.")
                        patches.append(feat_patch)
                except Exception: pass

            job.patches = patches
        except Exception as e:
            self._add_log(job, "ERROR", f"Coding session interrupted: {e}")
            return False
        return True

    # ---------- Phase: Validate ----------
    def run_phase_validate(self, job_id: str, build_cmd: Optional[str] = None,
                           test_cmd: Optional[str] = None) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        job.status = JobStatus.VALIDATING
        self._add_log(job, "INFO", "Agent starting code validation and build check...")
        try:
            from ase.validation.runner import SandboxRunner
            runner = SandboxRunner()
            reports = []
            for patch in job.patches:
                report = runner.run_validation(job.repo_path, build_cmd, test_cmd)
                report["patch_type"] = patch.get("patch_type", "unknown")
                report["patch_rule"] = patch.get("finding", {}).get("rule_id", patch.get("recommendation", {}).get("title", ""))
                reports.append(report)
                if report.get("status") == "success":
                    self._add_log(job, "SUCCESS", f"Validation passed for {report['patch_rule']}.")
                else:
                    self._add_log(job, "WARNING", f"Validation failed for {report['patch_rule']}: {report.get('error')}")
            job.validation_reports = reports
        except Exception as e:
            self._add_log(job, "ERROR", f"Validation process crashed: {e}")
            return False
        return True

    # ---------- Phase: Contribute ----------
    def run_phase_contribute(self, job_id: str, github_token: Optional[str] = None) -> bool:
        job = self._jobs.get(job_id)
        if not job: return False
        job.status = JobStatus.CONTRIBUTING
        self._add_log(job, "INFO", "Agent preparing contribution for GitHub...")
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
                    body = f"## AI Security Fix\n\n**Reasoning:**\n{patch.get('explanation')}\n\n**Impact:**\n{finding.get('message')}"
                    commit_msg = f"security: fix {cwe} in {finding.get('file_path', 'unknown')} [ASE-{job.job_id}]"

                self._add_log(job, "INFO", f"Submitting PR {i+1} to fork: {title}...")
                result = engine.create_pull_request(
                    repo_path=job.repo_path,
                    repo_slug=job.repo_slug,
                    branch_name=branch,
                    commit_msg=commit_msg,
                    pr_title=title,
                    pr_body=body,
                    dry_run=self.dry_run,
                )
                pr_results.append(result)
                if result.get("status") in ("success", "dry_run"):
                    self._add_log(job, "SUCCESS", f"Contribution successful: {result.get('pr_url') or 'Dry-run URL generated'}.")
            job.pr_results = pr_results
            job.status = JobStatus.DONE
        except Exception as e:
            self._add_log(job, "ERROR", f"Contribution failed: {e}")
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
        job = self._jobs[job_id]
        job.progress = 10
        self.run_phase_org_intelligence(job_id)
        job.progress = 30
        self.run_phase_analyze(job_id)
        job.progress = 50
        self.run_phase_reason(job_id)
        job.progress = 65
        self.run_phase_feature_recommendations(job_id)
        job.progress = 80
        self.run_phase_patch(job_id)
        job.progress = 90
        self.run_phase_validate(job_id, build_cmd, test_cmd)
        job.progress = 100
        self.run_phase_contribute(job_id, github_token)
        job.updated_at = datetime.utcnow().isoformat()
        return job
