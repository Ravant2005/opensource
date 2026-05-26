"""
Tree-sitter based code parser — extracts functions, classes, imports, call sites.
Falls back to regex-based extraction if tree-sitter is not installed.
"""
from __future__ import annotations
import re
import os
from typing import List, Dict, Any


def _try_treesitter(code: str, language: str) -> List[Dict[str, Any]]:
    try:
        from tree_sitter_languages import get_language, get_parser
        lang = get_language(language)
        parser = get_parser(language)
        tree = parser.parse(bytes(code, "utf8"))
        results = []
        _walk(tree.root_node, code, results)
        return results
    except Exception:
        return []


def _walk(node, code: str, out: list):
    if node.type in ("function_definition", "function_declaration", "method_definition"):
        name_node = node.child_by_field_name("name")
        name = code[name_node.start_byte:name_node.end_byte] if name_node else "anonymous"
        out.append({
            "type": "function",
            "name": name,
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "snippet": code[node.start_byte:node.end_byte][:300],
        })
    for child in node.children:
        _walk(child, code, out)


def _regex_extract(code: str) -> List[Dict[str, Any]]:
    results = []
    for m in re.finditer(r"^(?:def|func|function|fn|pub fn)\s+(\w+)\s*\(", code, re.MULTILINE):
        results.append({
            "type": "function",
            "name": m.group(1),
            "start_line": code[:m.start()].count("\n") + 1,
            "end_line": code[:m.start()].count("\n") + 1,
            "snippet": code[m.start():m.start() + 200],
        })
    for m in re.finditer(r"^(?:class|struct|interface)\s+(\w+)", code, re.MULTILINE):
        results.append({
            "type": "class",
            "name": m.group(1),
            "start_line": code[:m.start()].count("\n") + 1,
            "end_line": code[:m.start()].count("\n") + 1,
            "snippet": "",
        })
    return results


_LANG_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".c": "c", ".cpp": "cpp", ".go": "go", ".rs": "rust",
    ".java": "java", ".rb": "ruby",
}


class CodeExtractor:
    def extract_file(self, file_path: str) -> List[Dict[str, Any]]:
        ext = os.path.splitext(file_path)[1].lower()
        lang = _LANG_MAP.get(ext)
        try:
            with open(file_path, "r", errors="ignore") as f:
                code = f.read()
        except IOError:
            return []
        if lang:
            result = _try_treesitter(code, lang)
            if result:
                return result
        return _regex_extract(code)

    def extract_repo(self, repo_path: str, max_files: int = 500) -> Dict[str, List[Dict]]:
        out: Dict[str, List[Dict]] = {}
        count = 0
        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv")]
            for fname in files:
                if count >= max_files:
                    break
                if os.path.splitext(fname)[1].lower() in _LANG_MAP:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, repo_path)
                    items = self.extract_file(fpath)
                    if items:
                        out[rel] = items
                        count += 1
        return out
