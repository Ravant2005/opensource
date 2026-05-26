"""
Phase 3: Correlation Engine — maps intelligence → code gaps → ranked opportunities.
"""
from __future__ import annotations
import json
from ocis.core.llm.client import get_llm

_SCORING_PROMPT = """You are an expert open-source contribution strategist with years of experience contributing to top-tier projects like Linux, Kubernetes, and VS Code.
Your goal is to evaluate this contribution opportunity for the project "{project_name}" ({stars} stars) with surgical precision.

OPPORTUNITY: {title}
DESCRIPTION: {description}
EVIDENCE: {evidence}

Analyze this opportunity through the lens of a senior maintainer. Consider the technical debt, architectural impact, community demand, and long-term maintainability.

Score each metric on a 1.0-10.0 scale (1 decimal). Return ONLY valid JSON:
{{
  "impact_score": 0.0,
  "difficulty_score": 0.0,
  "novelty_score": 0.0,
  "visibility_score": 0.0,
  "feasibility_score": 0.0,
  "reasoning": "A deep, insightful analysis (3-4 sentences) explaining WHY this matters to the project's health and how it aligns with modern software engineering best practices.",
  "suggested_approach": "A world-class, high-level engineering strategy (4-6 sentences). Outline the architectural pattern to use, edge cases to handle, and how to ensure zero regressions.",
  "estimated_hours": 0,
  "risks": [
    "Identify a non-obvious technical risk or potential side effect."
  ]
}}"""


class CorrelationEngine:
    def __init__(self):
        self.llm = get_llm()

    def correlate(self, intelligence: dict, analysis: dict, log=None) -> list:
        def emit(msg):
            if log:
                log(msg)

        synthesis = intelligence.get("synthesis", {})
        gh = intelligence.get("github", {})
        meta = gh.get("metadata", {})
        project_name = intelligence.get("project_name", "unknown")
        stars = meta.get("stars", 0)
        repo_slug = intelligence.get("repo_slug", "")

        # Fetch past recommendations to ensure novelty
        from ocis.core.memory import get_memory
        past_titles = get_memory().get_all_past_recommendations(repo_slug)

        raw_opportunities = []

        # 1. From good-first-issues
        for issue in gh.get("good_first_issues", [])[:8]:
            if issue.get("title") in past_titles: continue
            raw_opportunities.append({
                "type": "bug_fix",
                "title": issue.get("title", ""),
                "description": (issue.get("body") or "")[:300],
                "evidence": {"github_issues": [f"#{issue.get('number')} {issue.get('url','')}"]},
                "source_weight": 0.8,
            })

        # 2. From help-wanted
        for issue in gh.get("help_wanted", [])[:8]:
            if issue.get("title") in past_titles: continue
            raw_opportunities.append({
                "type": "feature",
                "title": issue.get("title", ""),
                "description": (issue.get("body") or "")[:300],
                "evidence": {"github_issues": [f"#{issue.get('number')} {issue.get('url','')}"]},
                "source_weight": 0.9,
            })

        # 3. From pain points in synthesis
        for pp in synthesis.get("top_pain_points", [])[:5]:
            if pp.get("title") in past_titles: continue
            raw_opportunities.append({
                "type": "feature",
                "title": pp.get("title", ""),
                "description": pp.get("evidence", ""),
                "evidence": {"community_mentions": [pp.get("source", "")]},
                "source_weight": pp.get("frequency", 5) / 10,
            })

        # 4. From missing features
        for mf in synthesis.get("missing_features", [])[:5]:
            title = f"Add: {mf.get('feature', '')}"
            if title in past_titles: continue
            raw_opportunities.append({
                "type": "feature",
                "title": title,
                "description": f"Requested by {mf.get('requested_by', 'community')}",
                "evidence": {"community_mentions": ["synthesis"]},
                "source_weight": {"high": 0.9, "medium": 0.6, "low": 0.3}.get(
                    mf.get("priority", "medium"), 0.6),
            })

        # 5. From TODOs in code
        todos = analysis.get("todos", [])[:5]
        if todos:
            title = f"Resolve {len(todos)} TODO/FIXME comments in codebase"
            if title not in past_titles:
                raw_opportunities.append({
                    "type": "refactor",
                    "title": title,
                    "description": f"Found {len(todos)} unresolved technical debt markers.",
                    "evidence": {"code_location": {"files": list({t['file'] for t in todos[:5]})}},
                    "source_weight": 0.5,
                })

        # 6. Test coverage gaps
        test_gaps = analysis.get("test_coverage_gaps", [])
        if test_gaps:
            title = f"Add tests for {len(test_gaps)} untested modules"
            if title not in past_titles:
                raw_opportunities.append({
                    "type": "test",
                    "title": title,
                    "description": f"Modules without test coverage: {', '.join(test_gaps[:5])}",
                    "evidence": {"code_location": {"files": test_gaps[:5]}},
                    "source_weight": 0.6,
                })

        # 7. Doc gaps
        doc_gaps = analysis.get("doc_gaps", [])
        if doc_gaps:
            title = f"Add docstrings to {len(doc_gaps)} undocumented public functions"
            if title not in past_titles:
                raw_opportunities.append({
                    "type": "docs",
                    "title": title,
                    "description": "Improve API documentation coverage.",
                    "evidence": {"code_location": {"files": list({d['file'] for d in doc_gaps[:5]})}},
                    "source_weight": 0.4,
                })

        # 8. CI improvements
        ci = analysis.get("ci_analysis", {})
        if not ci.get("has_security"):
            title = "Add security scanning to CI pipeline"
            if title not in past_titles:
                raw_opportunities.append({
                    "type": "security",
                    "title": title,
                    "description": "No security scanner detected in CI. Add Semgrep or CodeQL.",
                    "evidence": {"code_location": {"files": ci.get("ci_files", [])}},
                    "source_weight": 0.7,
                })

        # 9. Critical Vulnerability Analysis (Phase 3 Upgrade)
        # Scan for common vulnerability patterns in analysis
        vulns = analysis.get("vulnerabilities", [])
        for v in vulns:
            title = f"Fix critical vulnerability: {v.get('type', 'security issue')}"
            if title in past_titles: continue
            raw_opportunities.append({
                "type": "security",
                "title": title,
                "description": v.get("description", "Potential security risk detected in static analysis."),
                "evidence": {"code_location": {"files": [v.get("file")]}},
                "source_weight": 1.0, # Highest priority
            })

        # 10. From Strategic Goals (Phase 3 Upgrade)
        goals = intelligence.get("synthesis", {}).get("strategic_goals", {})
        for goal_obj in goals.get("strategic_priorities", []):
            title = f"Upgrade: {goal_obj.get('goal', '')}"
            if title in past_titles: continue
            raw_opportunities.append({
                "type": "feature",
                "title": title,
                "description": goal_obj.get("description", ""),
                "evidence": {"strategic_goal": goal_obj.get("urgency", "high")},
                "source_weight": 0.95 if goal_obj.get("urgency") == "high" else 0.7,
            })

        # Ensure we have enough opportunities (minimum 5)
        if len(raw_opportunities) < 5:
            # If still low, ask LLM to brainstorm 'Staff Level' innovative features based on project state
            emit(f"Only {len(raw_opportunities)} signals found. Brainstorming advanced staff-level features to meet quota...")
            brainstorm_prompt = f"""You are a Principal Engineer and Open Source Strategist.
Project: {project_name} ({repo_slug})
Goals: {json.dumps(goals)}
Analysis Stats: {json.dumps(analysis.get('stats', {}))}

We found very few traditional issues/pain points. Based on the project's stars ({stars}) and purpose, 
recommend {5 - len(raw_opportunities)} highly innovative, non-obvious features or architectural 
improvements that would make this project 'top tier'. 

Focus on:
1. Architectural scalability.
2. Modern security hardening.
3. Developer experience (DX) improvements.

Return ONLY a JSON list of objects:
[
  {{"type": "feature", "title": "...", "description": "...", "evidence": {{"brainstorm": "Principal Engineer Insight"}}, "source_weight": 0.9}}
]"""
            try:
                extra = self.llm.chat_json([{"role": "user", "content": brainstorm_prompt}])
                if isinstance(extra, list) and extra:
                    # Ensure each extra item has the expected structure
                    for item in extra:
                        if isinstance(item, dict) and item.get("title"):
                            if item["title"] not in past_titles:
                                raw_opportunities.append(item)
                elif isinstance(extra, dict) and "opportunities" in extra:
                    # Some LLMs wrap it in an object even if asked for a list
                    for item in extra["opportunities"]:
                        if item.get("title") and item["title"] not in past_titles:
                            raw_opportunities.append(item)
                else:
                    emit("  Brainstorming returned no valid opportunities.")
            except Exception as e:
                emit(f"  Brainstorming failed: {e}")
                pass

        # Final safety net: if we STILL have fewer than 3, add deterministic defaults
        if len(raw_opportunities) < 3:
            emit("Quota still not met. Adding deterministic high-impact maintenance tasks...")
            defaults = [
                {
                    "type": "refactor", "title": "Comprehensive Code Audit and Style Alignment",
                    "description": "Perform a deep audit of the core modules to align with modern best practices.",
                    "evidence": {"fallback": "Autonomous Quota"}, "source_weight": 0.5
                },
                {
                    "type": "security", "title": "Implement Advanced Security Hardening",
                    "description": "Add comprehensive security headers, audit dependencies, and harden entry points.",
                    "evidence": {"fallback": "Autonomous Quota"}, "source_weight": 0.7
                },
                {
                    "type": "docs", "title": "Improve Architectural Documentation",
                    "description": "Create a high-level architectural overview to help new contributors.",
                    "evidence": {"fallback": "Autonomous Quota"}, "source_weight": 0.6
                }
            ]
            for d in defaults:
                if d["title"] not in past_titles and len(raw_opportunities) < 5:
                    raw_opportunities.append(d)

        emit(f"Scoring {len(raw_opportunities)} raw opportunities with LLM...")
        scored = []
        for i, opp in enumerate(raw_opportunities[:12]):
            emit(f"  Scoring opportunity {i+1}/{min(len(raw_opportunities), 12)}: {opp['title'][:50]}...")
            scores = self.llm.chat_json([{"role": "user", "content": _SCORING_PROMPT.format(
                project_name=project_name, stars=stars,
                title=opp["title"], description=opp["description"],
                evidence=json.dumps(opp["evidence"]),
            )}])
            if "error" in scores:
                scores = {"impact_score": 5.0, "difficulty_score": 5.0,
                          "novelty_score": 5.0, "visibility_score": 5.0,
                          "feasibility_score": 5.0, "reasoning": "LLM unavailable",
                          "suggested_approach": "", "estimated_hours": 8, "risks": []}

            impact = scores.get("impact_score", 5.0)
            difficulty = scores.get("difficulty_score", 5.0)
            novelty = scores.get("novelty_score", 5.0)
            visibility = scores.get("visibility_score", 5.0)
            
            # Phase 3 Upgrade: Boost score for Security and Strategic Goals
            type_multiplier = 1.0
            if opp["type"] == "security": type_multiplier = 1.3
            elif "strategic_goal" in opp.get("evidence", {}): type_multiplier = 1.2

            composite = round(
                (impact * 0.40 + novelty * 0.30 + visibility * 0.20 + (10 - difficulty) * 0.10) * type_multiplier, 2
            )
            scored.append({
                "id": f"opp_{i+1:03d}",
                "type": opp["type"],
                "title": opp["title"],
                "description": opp["description"],
                "evidence": opp["evidence"],
                "impact_score": impact,
                "difficulty_score": difficulty,
                "novelty_score": novelty,
                "visibility_score": visibility,
                "feasibility_score": scores.get("feasibility_score", 5.0),
                "composite_score": composite,
                "reasoning": scores.get("reasoning", ""),
                "suggested_approach": scores.get("suggested_approach", ""),
                "estimated_hours": scores.get("estimated_hours", 8),
                "risks": scores.get("risks", []),
                "pr_title_suggestion": f"{opp['type']}: {opp['title'][:60]}",
            })

        scored.sort(key=lambda x: -x["composite_score"])
        return scored[:10]
