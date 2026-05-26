"""
AI patch generator.
Produces minimal JSON payload: {status, patch, explanation}.
"""
from __future__ import annotations
import os
import re
import json
from typing import Dict, Any, Optional
from ase.config import GEMINI_API_KEY, GEMINI_MODEL

try:
    # Compatibility path used by tests.
    from google import generativeai as genai  # type: ignore
except Exception:  # pragma: no cover - fallback when SDK is missing
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
    if not api_key or api_key == "MOCK":
        return ""

    try:
        if hasattr(genai, "configure"):
            genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        prompt = f"System instruction:\n{system}\n\nUser request:\n{user}"
        response = model.generate_content(prompt, generation_config={"temperature": 0.1})
        text = getattr(response, "text", "") or ""
        if text:
            return text
    except Exception:
        pass

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


class PatchGenerator:
    def __init__(self, api_key: Optional[str] = None, model_name: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model_name = model_name or GEMINI_MODEL

    def generate_patch(self, finding: Dict[str, Any], code_context: str, reasoning_context: str) -> Dict[str, Any]:
        system = (
            "You are an elite Senior Software Engineer and AI Coding Agent. "
            "Your task is to implement a REAL, production-quality code fix for a security vulnerability. "
            "NEVER return placeholders, TODOs, or comments instead of code. "
            "You MUST return a valid Unified Diff that perfectly fixes the issue while preserving codebase style. "
            "Return ONLY valid JSON with keys: "
            "status ('success' or 'failed'), patch (unified diff string), explanation (string - Problem/Solution/Impact)."
        )
        user = (
            f"REASONING FROM SECURITY AGENT:\n{reasoning_context}\n\n"
            f"VULNERABILITY: {finding.get('rule_id')} at {finding.get('file_path')}:{finding.get('line_number')}\n"
            f"CODE CONTEXT:\n{code_context}\n\n"
            "Generate the REAL patch now. Ensure all necessary imports are included. "
            "The patch must be a valid unified diff (--- a/file ... +++ b/file ...). "
            "Return JSON only."
        )

        raw = _call_gemini(system, user, self.api_key, self.model_name)
        try:
            clean_raw = raw.strip()
            if clean_raw.startswith("```json"): clean_raw = clean_raw[7:]
            if clean_raw.endswith("```"): clean_raw = clean_raw[:-3]
            
            result = json.loads(clean_raw)
            if isinstance(result, dict) and result.get("patch"):
                # Strict check: reject if AI returned a mock/comment patch
                if "# TODO" in result["patch"] or "# FIXED" in result["patch"]:
                     raise ValueError("AI returned a placeholder comment instead of real code.")
                if "--- a/" not in result["patch"] or "+++ b/" not in result["patch"]:
                     raise ValueError("Invalid diff format.")
                return result
        except Exception:
            pass

        return {
            "status": "failed",
            "patch": "",
            "explanation": "Could not generate a valid real-world fix. The AI agent requires more context or the issue is too complex for automated patching.",
        }

    @staticmethod
    def apply_patch(target_file: str, patch_str: str) -> bool:
        """
        Minimal single-file hunk applier used by tests and dry-run flows.
        """
        if not os.path.exists(target_file):
            return False
        try:
            lines = open(target_file, encoding="utf-8").readlines()
        except IOError:
            return False

        hunks = []
        patch_lines = patch_str.splitlines()
        idx = 0
        while idx < len(patch_lines):
            line = patch_lines[idx]
            if line.startswith("@@"):
                m = re.match(r"^@@\s+-(\d+),?(\d+)?\s+\+(\d+),?(\d+)?\s+@@", line)
                if m:
                    old_start = int(m.group(1))
                    old_len = int(m.group(2) or 1)
                    content = []
                    idx += 1
                    while idx < len(patch_lines) and not patch_lines[idx].startswith("@@"):
                        content.append(patch_lines[idx])
                        idx += 1
                    hunks.append((old_start, old_len, content))
                    continue
            idx += 1

        hunks.sort(key=lambda x: x[0], reverse=True)
        for old_start, old_len, content in hunks:
            replacements = [l[1:] + "\n" for l in content if l.startswith("+")]
            lines[old_start - 1: old_start - 1 + old_len] = replacements

        try:
            open(target_file, "w", encoding="utf-8").writelines(lines)
            return True
        except IOError:
            return False
