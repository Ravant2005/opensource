"""
RepositoryImprovementAnalyzer \u2014 detects code quality, maintainability,
and best-practice issues beyond pure security vulnerabilities.
"""
from __future__ import annotations
import re
import os
from typing import List, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class ImprovementFinding:
    category: str       # code_quality | maintainability | performance | best_practice
    severity: str       # INFO | LOW | MEDIUM | HIGH
    file_path: str
    line_number: int
    title: str
    description: str
    suggestion: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        category = (self.category or "").replace("_", " ").title()
        d["finding_type"] = "improvement_fix"
        d["plain_explanation"] = (
            f"This is a {category} improvement — {self.suggestion} "
            f"in {self.file_path}."
        )
        return d


_PATTERNS: List[tuple] = [
    # (rule_id, regex, category, severity, title, description, suggestion)
    (
        "long-function",
        None,  # handled specially
        "maintainability", "MEDIUM",
        "Long function detected",
        "Functions over 60 lines are hard to test and review.",
        "Break into smaller, single-responsibility functions.",
    ),
    (
        "todo-fixme",
        re.compile(r"\b(TODO|FIXME|HACK|XXX)\b", re.IGNORECASE),
        "code_quality", "LOW",
        "Unresolved TODO/FIXME comment",
        "Unresolved technical debt marker found.",
        "Resolve or track in an issue tracker.",
    ),
    (
        "print-debug",
        re.compile(r"^\s*(print|console\.log|fmt\.Print|System\.out\.print)\s*\(", re.MULTILINE),
        "code_quality", "LOW",
        "Debug print statement",
        "Debug output left in production code.",
        "Remove or replace with structured logging.",
    ),
    (
        "bare-except",
        re.compile(r"except\s*:", re.MULTILINE),
        "best_practice", "MEDIUM",
        "Bare except clause",
        "Catches all exceptions including KeyboardInterrupt and SystemExit.",
        "Catch specific exception types.",
    ),
    (
        "hardcoded-ip",
        re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"),
        "best_practice", "LOW",
        "Hardcoded IP address",
        "IP addresses should come from configuration, not be hardcoded.",
        "Move to environment variable or config file.",
    ),
    (
        "magic-number",
        re.compile(r"(?<!['\"\w])(?<!def )(?<!class )\b(?!0\b|1\b|2\b)\d{3,}\b"),
        "code_quality", "LOW",
        "Magic number",
        "Unexplained numeric literal reduces readability.",
        "Extract to a named constant.",
    ),
    (
        "empty-catch",
        re.compile(r"except[^:]*:\s*\n\s*pass\b", re.MULTILINE),
        "best_practice", "MEDIUM",
        "Empty exception handler",
        "Silently swallowing exceptions hides bugs.",
        "Log the exception or re-raise it.",
    ),
    (
        "mutable-default-arg",
        re.compile(r"def\s+\w+\s*\([^)]*=\s*(\[\]|\{\}|\(\))", re.MULTILINE),
        "best_practice", "MEDIUM",
        "Mutable default argument",
        "Mutable default arguments are shared across all calls.",
        "Use None as default and initialise inside the function.",
    ),
    (
        "no-type-hints",
        re.compile(r"^def\s+\w+\s*\([^)]*\)\s*:", re.MULTILINE),
        "maintainability", "INFO",
        "Function missing type hints",
        "Type hints improve IDE support and catch bugs early.",
        "Add parameter and return type annotations.",
    ),
    (
        "global-var",
        re.compile(r"^\s*global\s+\w+", re.MULTILINE),
        "code_quality", "LOW",
        "Global variable mutation",
        "Global state makes code hard to test and reason about.",
        "Refactor to pass state explicitly or use a class.",
    ),
]

_CODE_EXTS = {".py", ".js", ".ts", ".go", ".java", ".c", ".cpp", ".rs", ".rb"}


class RepositoryImprovementAnalyzer:
    def analyze_file(self, file_path: str) -> List[ImprovementFinding]:
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in _CODE_EXTS:
            return []
        try:
            content = open(file_path, encoding="utf-8", errors="ignore").read()
        except IOError:
            return []

        findings: List[ImprovementFinding] = []
        lines = content.splitlines()

        # Long function detection (Python)
        if ext == ".py":
            findings.extend(self._detect_long_functions(file_path, lines))

        for rule_id, pattern, category, severity, title, description, suggestion in _PATTERNS:
            if pattern is None:
                continue
            for m in pattern.finditer(content):
                line_no = content[: m.start()].count("\n") + 1
                findings.append(
                    ImprovementFinding(
                        category=category,
                        severity=severity,
                        file_path=file_path,
                        line_number=line_no,
                        title=title,
                        description=description,
                        suggestion=suggestion,
                    )
                )

        return findings

    def _detect_long_functions(self, file_path: str, lines: List[str]) -> List[ImprovementFinding]:
        findings = []
        func_start = None
        func_name = ""
        indent_level = 0
        for i, line in enumerate(lines):
            m = re.match(r"^(\s*)def\s+(\w+)\s*\(", line)
            if m:
                if func_start is not None and (i - func_start) > 60:
                    findings.append(
                        ImprovementFinding(
                            category="maintainability",
                            severity="MEDIUM",
                            file_path=file_path,
                            line_number=func_start + 1,
                            title=f"Long function: {func_name}",
                            description=f"Function '{func_name}' is {i - func_start} lines long.",
                            suggestion="Break into smaller, single-responsibility functions.",
                        )
                    )
                func_start = i
                func_name = m.group(2)
                indent_level = len(m.group(1))
        return findings

    def analyze_repo(self, repo_path: str, max_files: int = 400) -> List[ImprovementFinding]:
        all_findings: List[ImprovementFinding] = []
        count = 0
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "__pycache__", ".venv"}]
            for fname in files:
                if count >= max_files:
                    return all_findings
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, repo_path)
                items = self.analyze_file(fpath)
                for item in items:
                    item.file_path = rel
                all_findings.extend(items)
                count += 1
        return all_findings
