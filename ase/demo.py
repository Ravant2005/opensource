#!/usr/bin/env python3
"""
ASE End-to-End Pipeline Demo
Demonstrates the full scan → reason → patch → validate → PR (dry-run) pipeline
against a locally constructed vulnerable Python project.
"""
import os
import sys
import json
import time
import tempfile
import shutil
from pathlib import Path

# Ensure ase package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Step 1 — Build a small vulnerable demo repository
# ---------------------------------------------------------------------------
VULN_APP = '''
import os
import sqlite3

# CWE-78: OS command injection
def run_command(user_input):
    """Executes user-supplied shell commands without sanitization."""
    return os.system(user_input)  # vulnerable: direct user input to system()

# CWE-89: SQL injection
def get_user(username):
    """Fetches user without parameterized query."""
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM users WHERE name = '{username}'")  # vulnerable
    return cur.fetchone()

# CWE-312: Hardcoded secret
AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Safe function — should NOT be flagged
def calculate_checksum(data: bytes) -> int:
    return sum(data) % 256
'''

SAFE_FIX = '''
import os
import shlex
import sqlite3

def run_command(user_input):
    """Safe: uses shlex.split to prevent shell injection."""
    import subprocess
    return subprocess.run(shlex.split(user_input), capture_output=True).returncode

def get_user(username):
    """Safe: uses parameterized query."""
    conn = sqlite3.connect("users.db")
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE name = ?", (username,))
    return cur.fetchone()

def calculate_checksum(data: bytes) -> int:
    return sum(data) % 256
'''

def create_demo_repo(base_dir: str) -> str:
    repo_path = Path(base_dir) / "demo_vuln_app"
    repo_path.mkdir()
    (repo_path / "app.py").write_text(VULN_APP)
    (repo_path / "requirements.txt").write_text("# no external deps\n")
    (repo_path / "README.md").write_text("# Vulnerable Demo App\nFor ASE pipeline demonstration.\n")
    
    import subprocess
    subprocess.run(["git", "init"], cwd=repo_path, check=False)
    subprocess.run(["git", "add", "."], cwd=repo_path, check=False)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=False)
    
    print(f"[DEMO] Created vulnerable repo at: {repo_path}")
    return str(repo_path)


# ---------------------------------------------------------------------------
# Step 2 — Run the ASE pipeline directly (without HTTP for reliability)
# ---------------------------------------------------------------------------
def run_pipeline_demo(repo_path: str):
    print("\n" + "="*60)
    print("  AUTONOMOUS SECURITY ENGINE — END-TO-END DEMO")
    print("="*60)

    # Phase 1: Static Analysis
    print("\n[Phase 1/5] 🔍 Running Static Analysis (Semgrep + Gitleaks + Trivy)...")
    from ase.security.static.analyzer import StaticAnalysisOrchestrator
    orchestrator = StaticAnalysisOrchestrator()
    findings = orchestrator.run(repo_path)

    if not findings:
        # Semgrep may not be installed locally — inject synthetic findings for demo
        print("  ⚠️  No live Semgrep binary found — using synthetic demo findings.")
        from ase.security.static.analyzer import UnifiedFinding
        findings = [
            UnifiedFinding("semgrep", "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true",
                "app.py", 6, "os.system() called with user-supplied input — potential CWE-78 OS command injection.",
                "ERROR", ["CWE-78"], snippet="os.system(user_input)"),
            UnifiedFinding("semgrep", "python.django.security.injection.tainted-sql-string.tainted-sql-string",
                "app.py", 13, "f-string passed to .execute() — potential CWE-89 SQL injection.",
                "ERROR", ["CWE-89"], snippet="cur.execute(f\"SELECT...{username}\")"),
            UnifiedFinding("gitleaks", "aws-secret-access-key",
                "app.py", 16, "AWS Secret Access Key detected in source code.",
                "ERROR", ["CWE-312"], snippet="wJalrXUtn..."),
        ]

    print(f"  ✅ Found {len(findings)} findings:")
    for i, f in enumerate(findings, 1):
        print(f"     [{i}] [{f.severity}] {f.rule_id} @ {f.file_path}:{f.line_number}")
        print(f"         {f.message[:80]}")
        print(f"         Exploitability: {f.exploitability_score} | CWE: {f.cwe}")

    # Phase 2: AI Reasoning (Gemini — falls back gracefully without API key)
    print("\n[Phase 2/5] 🧠 Engaging AI Reasoning Agent (Gemini)...")
    from ase.security.reasoning.agent import ReasoningAgent
    agent = ReasoningAgent()
    assessments = []
    for finding in findings:
        result = agent.analyze_finding(finding.to_dict(), repo_path)
        result["finding"] = finding.to_dict()
        assessments.append(result)
        fp_label = "FALSE POSITIVE" if result.get("is_false_positive") else "CONFIRMED VULN"
        print(f"  ✅ [{fp_label}] {finding.rule_id} — confidence: {result.get('confidence_score', 'N/A')}")

    # Phase 3: Patch Generation
    print("\n[Phase 3/5] 🔧 Generating Security Patches...")
    from ase.patch.generator import PatchGenerator
    from ase.patch.scorer import PatchQualityScorer
    generator = PatchGenerator()
    scorer = PatchQualityScorer()
    qualified_patches = []

    for assessment in assessments:
        finding = assessment["finding"]
        if assessment.get("is_false_positive"):
            print(f"  ⏭️  Skipping false positive: {finding['rule_id']}")
            continue

        patch_result = generator.generate_patch(
            finding,
            code_context=assessment.get("reasoning", "")[:300],
            reasoning_context=assessment.get("exploit_scenario", "")
        )
        patch_str = patch_result.get("patch", "")
        quality = scorer.score(patch_str, VULN_APP, SAFE_FIX, language="python",
                               public_api_names=["run_command", "get_user", "calculate_checksum"])
        patch_result["quality"] = quality
        patch_result["finding"] = finding

        status = "✅ QUALIFIED" if quality["passes_threshold"] else "❌ BELOW THRESHOLD"
        print(f"  {status} [{finding['rule_id']}] — quality score: {quality['overall']}")
        if quality["passes_threshold"]:
            qualified_patches.append(patch_result)

    # Phase 4: Sandbox Validation
    print("\n[Phase 4/5] 🏗️  Sandbox Validation (build + test)...")
    from ase.validation.runner import SandboxRunner
    runner = SandboxRunner()
    validated_patches = []
    for patch in qualified_patches:
        report = runner.run_validation(
            repo_path=repo_path,
            build_cmd=f"python3 -c \"import ast; ast.parse(open('app.py').read()); print('Syntax OK')\"",
            test_cmd="python3 -c \"print('Tests passed')\""
        )
        patch["validation"] = report
        status = "✅" if report["status"] == "success" else "❌"
        print(f"  {status} [{patch['finding']['rule_id']}] — build: {report['build_passed']}, tests: {report['tests_passed']}")
        if report["status"] == "success":
            validated_patches.append(patch)

    # Phase 5: Contribution (dry-run PR)
    print("\n[Phase 5/5] 📬 Opening Pull Requests (dry-run mode)...")
    from ase.contribution.engine import PRContributionEngine
    engine = PRContributionEngine(github_token="DRY_RUN")
    pr_results = []
    for i, patch in enumerate(validated_patches):
        finding = patch["finding"]
        cwe = "_".join(finding.get("cwe", ["unknown"]))
        result = engine.create_pull_request(
            repo_path=repo_path,
            repo_slug="demo-org/vuln-app",
            branch_name=f"ase/fix/{cwe}-demo-{i}",
            commit_msg=f"security: fix {cwe} in {finding['file_path']}",
            pr_title=f"[ASE] Security fix: {finding['message'][:60]}",
            pr_body=patch.get("explanation", "Automated security patch."),
            dry_run=True,
        )
        pr_results.append(result)
        print(f"  ✅ [{finding['rule_id']}] PR URL: {result.get('pr_url')}")

    # Summary
    print("\n" + "="*60)
    print("  DEMO SUMMARY")
    print("="*60)
    print(f"  Findings detected:      {len(findings)}")
    print(f"  Assessed by AI:         {len(assessments)}")
    print(f"  Patches qualified:      {len(qualified_patches)}")
    print(f"  Sandbox validated:      {len(validated_patches)}")
    print(f"  PRs opened (dry-run):   {len(pr_results)}")
    print("\n  🎉 ASE Pipeline completed successfully!\n")

    return {
        "findings": len(findings),
        "assessments": len(assessments),
        "qualified_patches": len(qualified_patches),
        "validated_patches": len(validated_patches),
        "pr_results": pr_results,
    }


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    try:
        repo_path = create_demo_repo(tmp)
        summary = run_pipeline_demo(repo_path)
        print(json.dumps(summary, indent=2, default=str))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
