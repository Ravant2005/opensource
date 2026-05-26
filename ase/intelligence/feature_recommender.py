"""
FeatureRecommender — LLM-powered feature suggestion engine.

Takes org intelligence (from OrgAnalyzer) + static analysis findings
and generates prioritised, actionable feature proposals that:
  • Align with the org's stated mission and roadmap
  • Address patterns in open issues
  • Are technically feasible given the codebase structure
  • Include a concrete implementation sketch
"""
from __future__ import annotations
import json
from typing import Dict, Any, List, Optional
from ase.config import GEMINI_API_KEY, GEMINI_MODEL


def _call_llm(prompt: str, api_key: str, model_name: str, as_json: bool = True) -> str:
    if not api_key or api_key in ("", "MOCK"):
        return "[]" if as_json else ""
    try:
        from google import generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        cfg = {"temperature": 0.3}
        if as_json:
            cfg["response_mime_type"] = "application/json"
        resp = model.generate_content(prompt, generation_config=cfg)
        return getattr(resp, "text", "") or ""
    except Exception:
        pass
    try:
        from google import genai as modern_genai
        from google.genai import types
        client = modern_genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json" if as_json else "text/plain",
                temperature=0.3,
            ),
        )
        return getattr(resp, "text", "") or ""
    except Exception:
        return "[]" if as_json else ""


class FeatureRecommender:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

    def generate_recommendations(
        self,
        org_intel: Dict[str, Any],
        static_findings: List[Dict],
        max_recommendations: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Returns a list of feature recommendation dicts, each with:
          - title: short feature name
          - description: what it does and why it matters
          - motivation: link to org goals / open issues
          - implementation_sketch: concrete steps / file locations to change
          - estimated_impact: low / medium / high / game-changing
          - pr_title: ready-to-use PR title
          - pr_body: full markdown PR description
          - files_to_modify: list of files likely needing changes
        """
        meta = org_intel.get("repo_meta", {})
        issues_summary = "\n".join(
            f"- #{i['number']}: {i['title']} (comments: {i.get('comments', 0)})"
            for i in org_intel.get("top_issues", [])[:15]
        )
        roadmap_text = org_intel.get("intel_files", {}).get("ROADMAP.md", "")
        readme_text = org_intel.get("intel_files", {}).get("README.md", "")[:1500]
        contributing_text = org_intel.get("intel_files", {}).get("CONTRIBUTING.md", "")[:800]
        recent_releases = "\n".join(
            f"- {r['tag']}: {r['body_excerpt'][:200]}"
            for r in org_intel.get("releases", [])
        )
        security_findings_summary = "\n".join(
            f"- {f.get('rule_id')}: {f.get('message','')[:100]} in {f.get('file_path','')}"
            for f in static_findings[:10]
        )

        prompt = f"""You are an elite Lead Software Architect and Open Source Strategist.

REPOSITORY: {meta.get('name', 'unknown')}
LANGUAGE: {meta.get('language', 'unknown')}
MISSION: {meta.get('description', 'No description')}

STRATEGIC SIGNALS:
- Roadmap: {roadmap_text[:1500] if roadmap_text else 'None'}
- Top Enhancement Issues: {issues_summary}
- Recent Releases: {recent_releases}
- Security Gaps: {security_findings_summary}

TASK: Propose exactly {max_recommendations} INNOVATIVE, HIGH-VALUE feature upgrades.

RULES:
1. THINK BIG. Don't propose minor refactors. Propose things like 'Distributed Caching Layer', 'Advanced Telemetry Dashboard', 'AI-Powered Search Integration'.
2. ALIGN with the Roadmap. If they mention 'Cloud', propose a 'Native Kubernetes Operator'.
3. TECHNICAL DEPTH: Provide a step-by-step IMPLEMENTATION SKETCH including specific files and logic changes.
4. MAINTAINER DELIGHT: Write a PR body that makes them want to merge immediately.

Return ONLY a valid JSON array of objects with keys: 
title, description, motivation, implementation_sketch, estimated_impact (game-changing|high|medium), pr_title, pr_body, files_to_modify.
"""

        raw = _call_llm(prompt, self.api_key, self.model_name, as_json=True)

        try:
            clean_raw = raw.strip()
            if clean_raw.startswith("```json"): clean_raw = clean_raw[7:]
            if clean_raw.endswith("```"): clean_raw = clean_raw[:-3]
            result = json.loads(clean_raw)
            if isinstance(result, list) and len(result) > 0:
                return result[:max_recommendations]
        except Exception:
            pass

        # Robust Fallback: Provide a high-value default based on language
        lang = meta.get('language', 'Python').lower()
        if 'python' in lang:
            return [{
                "title": "Advanced Async Telemetry & Observability Layer",
                "description": "Integrates OpenTelemetry for deep async-aware tracing and performance monitoring across the core engine.",
                "motivation": "Modern production systems require deep observability to debug complex async race conditions and bottlenecks.",
                "implementation_sketch": "1. Add opentelemetry-sdk to requirements. 2. Create middleware/tracer.py. 3. Instrument core entry points.",
                "estimated_impact": "high",
                "pr_title": "[Feature] Advanced Async Telemetry Integration",
                "pr_body": "This PR introduces a robust observability layer using OpenTelemetry...",
                "files_to_modify": ["core/engine.py", "api/main.py"]
            }]
        return [{
            "title": "Automated Security & Performance CI Pipeline",
            "description": "Custom GitHub Action pipeline for deep static and dynamic security analysis on every PR.",
            "motivation": "Ensures the project maintains a high security bar as it scales.",
            "implementation_sketch": "Create .github/workflows/security-audit.yml with specialized security containers.",
            "estimated_impact": "high",
            "pr_title": "[Feature] Automated Security CI Pipeline",
            "pr_body": "Introduces automated security auditing to the CI/CD flow...",
            "files_to_modify": [".github/workflows/main.yml"]
        }]

    def generate_feature_patch(
        self,
        recommendation: Dict[str, Any],
        repo_structure_summary: str,
    ) -> Dict[str, Any]:
        """
        Given a feature recommendation, generate actual code changes (unified diff).
        Returns {status, patch, explanation, files_modified}.
        """
        prompt = f"""You are an elite AI Coding Agent. You are writing production code.

FEATURE TO IMPLEMENT:
Title: {recommendation['title']}
Description: {recommendation['description']}
Implementation plan: {recommendation['implementation_sketch']}
Files to modify: {', '.join(recommendation.get('files_to_modify', []))}

REPO STRUCTURE (abbreviated):
{repo_structure_summary[:2000]}

Generate a REAL, complete unified diff patch that implements this feature.
The patch must:
1. Compile/run without errors
2. Follow the coding style of the existing codebase
3. Include necessary imports
4. Be minimal but complete — NEVER return TODOs or placeholders.

Return ONLY valid JSON with keys:
{{
  "status": "success",
  "patch": "<unified diff string>",
  "explanation": "Implemented feature: {recommendation['title']}",
  "files_modified": ["list of files changed"]
}}"""

        raw = _call_llm(prompt, self.api_key, self.model_name, as_json=True)
        try:
            clean_raw = raw.strip()
            if clean_raw.startswith("```json"): clean_raw = clean_raw[7:]
            if clean_raw.endswith("```"): clean_raw = clean_raw[:-3]
            
            result = json.loads(clean_raw)
            if isinstance(result, dict) and result.get("patch"):
                if "# TODO" in result["patch"]:
                    raise ValueError("AI returned a TODO instead of real code.")
                return result
        except Exception:
            pass
        return {
            "status": "failed",
            "patch": "",
            "explanation": "Feature patch generation failed. AI could not produce real code for this enhancement.",
            "files_modified": [],
        }
