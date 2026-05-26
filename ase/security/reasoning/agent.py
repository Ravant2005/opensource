"""
AI Security Reasoning Agent.
Builds context from source + graph + historical fixes and returns structured JSON.
"""
from __future__ import annotations
import os
import json
from typing import Dict, Any, Optional
from ase.config import GEMINI_API_KEY, GEMINI_MODEL

try:
    # Compatibility for existing tests and environments using google-generativeai.
    from google import generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - fallback for environments without the SDK
    class _MissingModel:
        def __init__(self, *args, **kwargs):
            pass

        def generate_content(self, *args, **kwargs):
            class _Resp:
                text = ""
            return _Resp()

    class _GenAICompat:
        GenerativeModel = _MissingModel

        @staticmethod
        def configure(*args, **kwargs):
            return None

    genai = _GenAICompat()  # type: ignore


def _call_gemini(system: str, user: str, api_key: str, model_name: str) -> str:
    """
    Multi-SDK Gemini call:
    1) `google.generativeai` compatibility path (preferred for current tests)
    2) `google.genai` modern SDK fallback
    """
    if not api_key or api_key == "MOCK":
        return ""

    # Path 1: google-generativeai
    try:
        if hasattr(genai, "configure"):
            genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = f"System instruction:\n{system}\n\nUser request:\n{user}"
        response = model.generate_content(
            prompt,
            generation_config={"temperature": 0.1},
        )
        text = getattr(response, "text", "") or ""
        if text:
            return text
    except Exception:
        pass

    # Path 2: google-genai
    try:
        from google import genai as modern_genai
        from google.genai import types

        client = modern_genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        return getattr(response, "text", "") or ""
    except Exception:
        return ""


class ReasoningAgent:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

    def extract_ast_snippet(self, repo_path: str, file_path: str, line: int, context_window: int = 10) -> str:
        full = os.path.join(repo_path, file_path)
        if not os.path.exists(full):
            return f"(file not found: {file_path})"
        try:
            lines = open(full, encoding="utf-8", errors="ignore").readlines()
        except IOError:
            return ""
        start = max(0, line - context_window - 1)
        end = min(len(lines), line + context_window)
        out = []
        for i in range(start, end):
            marker = "--> " if i + 1 == line else "    "
            out.append(f"{marker}{i+1:4d} | {lines[i]}")
        return "".join(out)

    def compile_context(
        self,
        finding: Dict[str, Any],
        repo_path: str,
        graph_layer: Optional[Any] = None,
        rag_layer: Optional[Any] = None,
    ) -> Dict[str, Any]:
        ast = self.extract_ast_snippet(
            repo_path,
            finding.get("file_path", ""),
            int(finding.get("line_number", 1)),
            context_window=10,
        )

        graph_callers = []
        if graph_layer is not None and hasattr(graph_layer, "find_all_callers"):
            try:
                graph_callers = graph_layer.find_all_callers(finding.get("rule_id", "unknown"))
            except Exception:
                graph_callers = []

        rag_fixes = []
        if rag_layer is not None and hasattr(rag_layer, "find_historical_fixes"):
            try:
                vuln_key = " ".join(finding.get("cwe", [])) or finding.get("rule_id", "")
                rag_fixes = rag_layer.find_historical_fixes(vuln_key, top_k=3)
            except Exception:
                rag_fixes = []

        return {
            "ast": ast,
            "graph_callers": graph_callers,
            "rag_fixes": rag_fixes,
        }

    def analyze_finding(
        self,
        finding: Dict[str, Any],
        repo_path: str,
        graph_layer: Optional[Any] = None,
        rag_layer: Optional[Any] = None,
    ) -> Dict[str, Any]:
        context = self.compile_context(finding, repo_path, graph_layer, rag_layer)
        snippet = context["ast"]
        callers = context["graph_callers"][:5]
        historical = context["rag_fixes"][:3]

        system = (
            "You are an elite Lead Security Engineer and Software Architect. "
            "Analyze the provided security finding and codebase context. "
            "Be aggressive in identifying REAL impact — do not dismiss findings easily unless they are obviously false positives. "
            "Think about data flow, untrusted input sources, and execution sinks. "
            "Return ONLY valid JSON with keys: "
            "is_false_positive (bool), confidence_score (float 0-1), "
            "exploit_scenario (string - detailed step-by-step), "
            "actionable_impact_explanation (string - what happens to the system), "
            "reasoning (string - your deep engineering logic)."
        )
        user = (
            f"VULNERABILITY: {finding.get('rule_id')} ({finding.get('message')})\n"
            f"LOCATION: {finding.get('file_path')}:{finding.get('line_number')}\n"
            f"SEVERITY: {finding.get('severity')} | CWE: {finding.get('cwe')}\n\n"
            f"CODE CONTEXT (with line markers):\n{snippet}\n\n"
            f"REACHABILITY DATA:\nCallers: {json.dumps(callers)}\n"
            f"HISTORICAL FIX PATTERNS:\n{json.dumps(historical)}\n\n"
            "Analyze deeply. How would an attacker trigger this? What's the fix strategy? "
            "Return JSON only."
        )

        raw = _call_gemini(system, user, self.api_key, self.model_name)
        try:
            result = json.loads(raw)
            if isinstance(result, dict):
                return result
        except Exception:
            pass

        return {
            "is_false_positive": False,
            "confidence_score": 0.6,
            "exploit_scenario": (
                f"Potential exploit path for {finding.get('rule_id')} at "
                f"{finding.get('file_path')}:{finding.get('line_number')}"
            ),
            "actionable_impact_explanation": "Default impact explanation: Issue could lead to system compromise. Please review manually.",
            "reasoning": (
                f"Static analysis flagged {finding.get('rule_id')} ({finding.get('message')}). "
                "Manual review advised."
            ),
        }
