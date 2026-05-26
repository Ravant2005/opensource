"""
PatchQualityScorer — Phase 3.3
Scores generated patches on minimality, style conformance, API stability,
and false-fix detection. Patches must score > 0.75 to proceed to validation.
"""
from __future__ import annotations
import re
from typing import Dict, Any, Optional


class PatchQualityScorer:
    PASS_THRESHOLD = 0.75

    def score(self, patch_str: str, original_code: str, patched_code: str,
              language: str = "python", public_api_names: Optional[list] = None) -> Dict[str, Any]:
        minimal_score = self._minimal_diff_score(patch_str)
        style_score = self._style_conformance_score(patched_code, language)
        api_score = self._api_stability_score(original_code, patched_code, public_api_names or [])
        false_fix_score = self._false_fix_detection_score(patched_code)
        overall = round(0.30 * minimal_score + 0.25 * style_score + 0.25 * api_score + 0.20 * false_fix_score, 3)
        return {
            "overall": overall,
            "passes_threshold": overall >= self.PASS_THRESHOLD,
            "minimal_diff_score": round(minimal_score, 3),
            "style_conformance_score": round(style_score, 3),
            "api_stability_score": round(api_score, 3),
            "false_fix_detection_score": round(false_fix_score, 3),
        }

    def _minimal_diff_score(self, patch_str: str) -> float:
        added = deleted = context = 0
        for line in patch_str.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                deleted += 1
            elif line.startswith(" "):
                context += 1
        total_changed = added + deleted
        if total_changed == 0:
            return 0.0
        return min((total_changed / max(total_changed + context, 1)) * 2.0, 1.0)

    def _style_conformance_score(self, patched_code: str, language: str) -> float:
        if language in ("python", "py"):
            try:
                compile(patched_code, "<patch>", "exec")
                return 1.0
            except SyntaxError:
                return 0.0
        opens, closes = patched_code.count("{"), patched_code.count("}")
        return 1.0 if opens == closes else 0.5

    def _api_stability_score(self, original_code: str, patched_code: str, public_api_names: list) -> float:
        if not public_api_names:
            return 1.0
        violations = 0
        for name in public_api_names:
            orig = self._extract_signature(original_code, name)
            patched = self._extract_signature(patched_code, name)
            if orig and patched and orig != patched:
                violations += 1
            elif orig and not patched:
                violations += 2
        return max(0.0, 1.0 - violations / max(len(public_api_names), 1))

    def _extract_signature(self, code: str, func_name: str) -> Optional[str]:
        m = re.search(rf"def\s+{re.escape(func_name)}\s*\([^)]*\)", code)
        if m:
            return m.group(0)
        m = re.search(rf"\b{re.escape(func_name)}\s*\([^)]*\)", code)
        return m.group(0) if m else None

    _VULN_PATTERNS = {
        "command_injection": re.compile(r"\bos\.system\s*\(\s*[^\"\']+\)"),
        "sql_injection": re.compile(r'execute\s*\(\s*[f"\']+.*%s'),
        "buffer_no_bounds": re.compile(r"\bgets\s*\("),
    }

    def _false_fix_detection_score(self, patched_code: str) -> float:
        issues = sum(1 for p in self._VULN_PATTERNS.values() if p.search(patched_code))
        return max(0.0, 1.0 - issues * 0.25)
