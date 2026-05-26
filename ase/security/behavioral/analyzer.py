"""
BehavioralAnalyzer:
1) `analyze_functions` compatibility API for structured function models.
2) `analyze_repo` lightweight repository scan for API/dashboard usage.
"""
from __future__ import annotations
import re
import os
from typing import List, Dict, Any
from dataclasses import dataclass, asdict, field


# ---------------------------------------------------------------------------
# Plain-English explanations for behavioral finding categories
# ---------------------------------------------------------------------------
_PLAIN_BEHAVIORAL: Dict[str, str] = {
    "race_condition": "This function touches shared state but has no lock or mutex protecting it. Two threads running at the same time can corrupt data or crash the program.",
    "privilege_escalation": "This function calls a privileged operation (like setuid) without confirming the caller is authorised to do so. An attacker who triggers this path gains root-level access.",
    "unsafe_memory": "Potentially unsafe memory operations were detected: dynamic allocation (malloc) combined with bounded copy (strcpy/sprintf/gets), or a pointer that appears to be used after being freed. This is a classic memory-corruption pattern that attackers often exploit.",
}


@dataclass
class BehavioralFinding:
    category: str
    description: str
    file_path: str
    function_name: str = ""
    evidence: List[str] = field(default_factory=list)
    severity: str = "MEDIUM"
    line_number: int = 1

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        category = self.category or ""
        d["finding_type"] = "behavioral_fix"
        d["plain_explanation"] = _PLAIN_BEHAVIORAL.get(
            category,
            self.description,
        )
        return d


class BehavioralAnalyzer:
    _RACE_KEYWORDS = ("pthread_mutex_lock", "mutex.Lock", "lock.acquire", "sync.Mutex")
    _PRIV_PATTERNS = re.compile(r"\bsetuid\s*\(|\bseteuid\s*\(|\bcap_set_proc\b|\bos\.setuid\b")
    _UNSAFE_MALLOC = re.compile(r"\bmalloc\s*\(")
    _UNSAFE_COPY = re.compile(r"\b(strcpy|strcat|sprintf|gets)\s*\(")
    _FREE_PTR = re.compile(r"\bfree\s*\(\s*([a-zA-Z_]\w*)\s*\)")

    def analyze_functions(self, functions: List[Dict[str, Any]]) -> List[BehavioralFinding]:
        findings: List[BehavioralFinding] = []

        for fn in functions:
            name = fn.get("name", "unknown")
            file_path = fn.get("file_path", "")
            body = fn.get("body", "") or ""
            accesses_globals = bool(fn.get("accesses_globals", False))
            evidence: List[str] = []

            # Race condition: global/shared state accessed without visible lock.
            if accesses_globals:
                has_mutex = any(k in body for k in self._RACE_KEYWORDS)
                if not has_mutex:
                    findings.append(BehavioralFinding(
                        category="race_condition",
                        description="Shared/global state accessed without visible synchronization.",
                        file_path=file_path,
                        function_name=name,
                        evidence=["global-state access without mutex"],
                        severity="HIGH",
                        line_number=1,
                    ))

            # Privilege escalation patterns.
            if self._PRIV_PATTERNS.search(body):
                evidence.append("privileged API call (setuid/capability)")
                findings.append(BehavioralFinding(
                    category="privilege_escalation",
                    description="Function reaches privileged operation from regular execution path.",
                    file_path=file_path,
                    function_name=name,
                    evidence=evidence[:] or ["setuid/capability usage"],
                    severity="CRITICAL",
                    line_number=1,
                ))

            # Unsafe memory patterns (C/C++).
            has_malloc = bool(self._UNSAFE_MALLOC.search(body))
            has_unsafe_copy = bool(self._UNSAFE_COPY.search(body))
            free_match = self._FREE_PTR.search(body)
            uaf_detected = False
            if free_match:
                ptr_name = free_match.group(1)
                after_free = body[free_match.end():]
                if re.search(rf"\b{re.escape(ptr_name)}\b\s*(?:->|\.|\[|=)", after_free):
                    uaf_detected = True

            if (has_malloc and has_unsafe_copy) or uaf_detected:
                mem_evidence: List[str] = []
                if has_malloc:
                    mem_evidence.append("malloc without bounds verification nearby")
                if has_unsafe_copy:
                    mem_evidence.append("unsafe copy function used (strcpy/gets/sprintf)")
                if uaf_detected:
                    mem_evidence.append("possible use-after-free after free(ptr)")
                findings.append(BehavioralFinding(
                    category="unsafe_memory",
                    description="Potential unsafe memory handling pattern detected.",
                    file_path=file_path,
                    function_name=name,
                    evidence=mem_evidence,
                    severity="HIGH",
                    line_number=1,
                ))

        return findings

    def analyze_file(self, file_path: str) -> List[BehavioralFinding]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except IOError:
            return []

        # Convert file content into a pseudo-function model for compatibility logic.
        pseudo_fn = {
            "name": os.path.basename(file_path),
            "file_path": file_path,
            "body": content,
            "calls": [],
            "accesses_globals": bool(re.search(r"\b(global|static)\b", content)),
        }
        findings = self.analyze_functions([pseudo_fn])

        # Attach best-effort line numbers for repository view.
        for finding in findings:
            if finding.category == "privilege_escalation":
                m = self._PRIV_PATTERNS.search(content)
                if m:
                    finding.line_number = content[:m.start()].count("\n") + 1
            elif finding.category == "unsafe_memory":
                m = self._UNSAFE_COPY.search(content) or self._UNSAFE_MALLOC.search(content)
                if m:
                    finding.line_number = content[:m.start()].count("\n") + 1
            elif finding.category == "race_condition":
                finding.line_number = 1
        return findings

    def analyze_repo(self, repo_path: str, max_files: int = 300) -> List[BehavioralFinding]:
        all_findings: List[BehavioralFinding] = []
        exts = {".py", ".c", ".cpp", ".go", ".rs", ".java", ".js", ".ts"}
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
            for fname in files:
                if os.path.splitext(fname)[1].lower() not in exts:
                    continue
                all_findings.extend(self.analyze_file(os.path.join(root, fname)))
                if len(all_findings) >= max_files:
                    return all_findings
        return all_findings
