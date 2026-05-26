import os
import json
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Any, Optional, Iterator
import git
from pygments.lexers import get_lexer_for_filename, ClassNotFound
from tree_sitter import Language, Parser
import tree_sitter_python as tspython
import tree_sitter_c as tsc
import tree_sitter_go as tsgo
import tree_sitter_rust as tsrust
import tree_sitter_java as tsjava
import tree_sitter_javascript as tsjs

class RepoIngestionPipeline:
    def __init__(self, staging_dir: Optional[str] = None):
        """
        Initializes the repository ingestion pipeline.
        :param staging_dir: Directory where the output structured JSON files will be written.
                            If None, a temporary directory will be created.
        """
        self.staging_dir = Path(staging_dir) if staging_dir else Path(tempfile.mkdtemp(prefix="ase_staging_"))
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        # Load modern tree-sitter language libraries
        self.languages = {
            "python": Language(tspython.language()),
            "c": Language(tsc.language()),
            "go": Language(tsgo.language()),
            "rust": Language(tsrust.language()),
            "java": Language(tsjava.language()),
            "javascript": Language(tsjs.language())
        }
        
        self.parsers = {lang: Parser(obj) for lang, obj in self.languages.items()}

    def detect_language(self, filepath: Path) -> Optional[str]:
        """
        Detects if a file is written in one of the supported languages.
        First tries file extension, then falls back to Pygments lexer detection.
        """
        ext = filepath.suffix.lower()
        ext_map = {
            ".py": "python",
            ".c": "c",
            ".h": "c",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".js": "javascript",
            ".jsx": "javascript",
            ".ts": "javascript",
            ".tsx": "javascript"
        }
        if ext in ext_map:
            return ext_map[ext]
            
        try:
            with open(filepath, "r", errors="ignore") as f:
                content = f.read(1024)
            lexer = get_lexer_for_filename(filepath.name, code=content)
            lexer_name = lexer.name.lower()
            if "python" in lexer_name:
                return "python"
            elif "c" in lexer_name:
                return "c"
            elif "go" in lexer_name:
                return "go"
            elif "rust" in lexer_name:
                return "rust"
            elif "java" in lexer_name:
                return "java"
            elif "javascript" in lexer_name or "typescript" in lexer_name:
                return "javascript"
        except ClassNotFound:
            pass
        return None

    def ingest(self, repo_url: str) -> Path:
        """
        Clones a repository, walks its files, detects language, parses code,
        and streams structured JSON objects representing repository intelligence.
        """
        temp_dir = tempfile.mkdtemp(prefix="ase_repo_")
        try:
            print(f"Cloning repository {repo_url} to {temp_dir}...")
            git.Repo.clone_from(repo_url, temp_dir, depth=1)
            self.process_directory(Path(temp_dir))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
            
        return self.staging_dir

    def process_directory(self, repo_path: Path):
        """
        Iterates over the cloned repository structure without keeping everything in memory.
        """
        for root, _, files in os.walk(repo_path):
            for file in files:
                filepath = Path(root) / file
                if filepath.is_symlink():
                    continue
                lang = self.detect_language(filepath)
                if lang:
                    try:
                        self.process_file(filepath, repo_path, lang)
                    except Exception as e:
                        print(f"Error processing {filepath}: {e}")

    def process_file(self, filepath: Path, repo_path: Path, language: str):
        """
        Parses a single file using the appropriate tree-sitter parser,
        extracts structural patterns, and writes a streaming JSON to the staging area.
        """
        relative_path = filepath.relative_to(repo_path)
        
        try:
            with open(filepath, "rb") as f:
                source_code = f.read()
        except IOError:
            return

        parser = self.parsers.get(language)
        if not parser:
            return

        tree = parser.parse(source_code)
        
        # Extract features
        extractor = ASTExtractor(source_code, language)
        extractor.visit(tree.root_node)
        
        file_summary = {
            "file_path": str(relative_path),
            "language": language,
            "functions": extractor.functions,
            "classes": extractor.classes,
            "imports": extractor.imports,
            "call_sites": extractor.call_sites,
            "globals": extractor.globals
        }
        
        # Stream JSON to staging directory
        safe_name = str(relative_path).replace("/", "_").replace("\\", "_") + ".json"
        out_path = self.staging_dir / safe_name
        with open(out_path, "w", encoding="utf-8") as out_f:
            json.dump(file_summary, out_f, indent=2)


class ASTExtractor:
    def __init__(self, source_code: bytes, language: str):
        self.source_code = source_code
        self.language = language
        
        self.functions: List[Dict[str, Any]] = []
        self.classes: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []
        self.call_sites: List[Dict[str, Any]] = []
        self.globals: List[Dict[str, Any]] = []
        
        self.current_class: Optional[str] = None

    def get_text(self, node) -> str:
        if not node:
            return ""
        return self.source_code[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def visit(self, node):
        node_type = node.type
        
        # ------------------ LANGUAGE SPECIFIC EXTRACTORS ------------------
        
        if self.language == "python":
            if node_type == "function_definition":
                name_node = node.child_by_field_name("name")
                name = self.get_text(name_node)
                
                # Parameters
                params = []
                params_node = node.child_by_field_name("parameters")
                if params_node:
                    params = [self.get_text(c) for c in params_node.children if c.type == "identifier" or c.type == "typed_parameter"]

                # Return type
                ret_node = node.child_by_field_name("return_type")
                ret_type = self.get_text(ret_node) if ret_node else None

                self.functions.append({
                    "name": name,
                    "signature": f"def {name}(...)" + (f" -> {ret_type}" if ret_type else ""),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "parameters": params,
                    "return_type": ret_type,
                    "enclosing_class": self.current_class
                })
                
            elif node_type == "class_definition":
                name_node = node.child_by_field_name("name")
                name = self.get_text(name_node)
                
                # Base classes
                bases = []
                bases_node = node.child_by_field_name("superclasses")
                if bases_node:
                    bases = [self.get_text(c) for c in bases_node.children if c.type in ("identifier", "attribute")]

                self.classes.append({
                    "name": name,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "bases": bases
                })
                
                # Enter class context
                prev_class = self.current_class
                self.current_class = name
                for child in node.children:
                    self.visit(child)
                self.current_class = prev_class
                return

            elif node_type in ("import_statement", "import_from_statement"):
                self.imports.append({
                    "raw": self.get_text(node).strip(),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "call":
                func_node = node.child_by_field_name("function")
                func_name = self.get_text(func_node)
                self.call_sites.append({
                    "name": func_name,
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "assignment" and node.parent and node.parent.parent and node.parent.parent.type == "module":
                # Top level globals in module
                left_node = node.child_by_field_name("left")
                if left_node and left_node.type == "identifier":
                    self.globals.append({
                        "name": self.get_text(left_node),
                        "start_line": node.start_point[0] + 1
                    })

        elif self.language == "c":
            if node_type == "function_definition":
                declarator = node.child_by_field_name("declarator")
                func_name = ""
                # Dive in to find identifier
                curr = declarator
                while curr:
                    if curr.type == "identifier":
                        func_name = self.get_text(curr)
                        break
                    elif curr.type == "function_declarator":
                        curr = curr.child_by_field_name("declarator")
                    elif curr.type == "pointer_declarator":
                        curr = curr.children[-1]
                    elif curr.type == "parenthesized_declarator":
                        curr = curr.children[1]
                    else:
                        if curr.children:
                            curr = curr.children[0]
                        else:
                            break

                self.functions.append({
                    "name": func_name or "unknown",
                    "signature": self.get_text(node.child_by_field_name("type") or declarator),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": None
                })

            elif node_type in ("struct_specifier", "union_specifier"):
                name_node = node.child_by_field_name("name")
                if name_node:
                    self.classes.append({
                        "name": self.get_text(name_node),
                        "start_line": node.start_point[0] + 1,
                        "end_line": node.end_point[0] + 1,
                        "bases": []
                    })

            elif node_type == "preproc_include":
                path_node = node.child_by_field_name("path")
                self.imports.append({
                    "raw": self.get_text(path_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "call_expression":
                func_node = node.child_by_field_name("function")
                self.call_sites.append({
                    "name": self.get_text(func_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "declaration" and node.parent and node.parent.type == "translation_unit":
                # Global variables in C
                dec_node = node.child_by_field_name("declarator")
                if dec_node and dec_node.type == "identifier":
                    self.globals.append({
                        "name": self.get_text(dec_node),
                        "start_line": node.start_point[0] + 1
                    })

        elif self.language == "go":
            if node_type == "function_declaration":
                name_node = node.child_by_field_name("name")
                self.functions.append({
                    "name": self.get_text(name_node),
                    "signature": f"func {self.get_text(name_node)}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": None
                })
            elif node_type == "method_declaration":
                name_node = node.child_by_field_name("name")
                receiver_node = node.child_by_field_name("receiver")
                receiver = self.get_text(receiver_node) if receiver_node else None
                if receiver:
                    receiver = receiver.strip("()").split()[-1]
                self.functions.append({
                    "name": self.get_text(name_node),
                    "signature": f"func ({receiver}) {self.get_text(name_node)}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": receiver
                })
            elif node_type == "type_declaration":
                # Check for structs
                for child in node.children:
                    if child.type == "type_spec":
                        name_node = child.child_by_field_name("name")
                        type_node = child.child_by_field_name("type")
                        if type_node and type_node.type in ("struct_type", "interface_type"):
                            self.classes.append({
                                "name": self.get_text(name_node),
                                "start_line": node.start_point[0] + 1,
                                "end_line": node.end_point[0] + 1,
                                "bases": []
                            })

            elif node_type == "import_spec":
                path_node = node.child_by_field_name("path")
                self.imports.append({
                    "raw": self.get_text(path_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "call_expression":
                func_node = node.child_by_field_name("function")
                self.call_sites.append({
                    "name": self.get_text(func_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type in ("var_declaration", "const_declaration") and node.parent and node.parent.type == "source_file":
                # Find variable names inside var/const declarations
                for spec in node.children:
                    if spec.type in ("var_spec", "const_spec"):
                        names_node = spec.child_by_field_name("name") or spec.child_by_field_name("names")
                        if names_node:
                            self.globals.append({
                                "name": self.get_text(names_node),
                                "start_line": node.start_point[0] + 1
                            })

        elif self.language == "rust":
            if node_type == "function_item":
                name_node = node.child_by_field_name("name")
                self.functions.append({
                    "name": self.get_text(name_node),
                    "signature": f"fn {self.get_text(name_node)}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": self.current_class
                })
            elif node_type == "impl_item":
                # Record impl block for class mapping
                type_node = node.child_by_field_name("type")
                name = self.get_text(type_node)
                self.classes.append({
                    "name": name,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "bases": []
                })
                prev_class = self.current_class
                self.current_class = name
                for child in node.children:
                    self.visit(child)
                self.current_class = prev_class
                return
            elif node_type in ("struct_item", "enum_item", "union_item"):
                name_node = node.child_by_field_name("name")
                self.classes.append({
                    "name": self.get_text(name_node),
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "bases": []
                })

            elif node_type == "use_declaration":
                self.imports.append({
                    "raw": self.get_text(node).strip(),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "call_expression":
                func_node = node.child_by_field_name("function")
                self.call_sites.append({
                    "name": self.get_text(func_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type in ("const_item", "static_item") and node.parent and node.parent.type == "source_file":
                name_node = node.child_by_field_name("name")
                if name_node:
                    self.globals.append({
                        "name": self.get_text(name_node),
                        "start_line": node.start_point[0] + 1
                    })

        elif self.language == "java":
            if node_type == "method_declaration":
                name_node = node.child_by_field_name("name")
                type_node = node.child_by_field_name("type")
                ret_type = self.get_text(type_node) if type_node else "void"
                self.functions.append({
                    "name": self.get_text(name_node),
                    "signature": f"{ret_type} {self.get_text(name_node)}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": self.current_class
                })
            elif node_type == "class_declaration" or node_type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                name = self.get_text(name_node)
                self.classes.append({
                    "name": name,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "bases": []
                })
                prev_class = self.current_class
                self.current_class = name
                for child in node.children:
                    self.visit(child)
                self.current_class = prev_class
                return

            elif node_type == "import_declaration":
                name_node = node.children[1]  # usually the imported path
                self.imports.append({
                    "raw": self.get_text(name_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "method_invocation":
                name_node = node.child_by_field_name("name")
                self.call_sites.append({
                    "name": self.get_text(name_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "field_declaration" and self.current_class:
                # Java fields count as class-level variables (closest to globals)
                dec_node = node.child_by_field_name("declarator")
                if dec_node:
                    name_node = dec_node.child_by_field_name("name")
                    if name_node:
                        self.globals.append({
                            "name": self.get_text(name_node),
                            "start_line": node.start_point[0] + 1
                        })

        elif self.language == "javascript":
            if node_type in ("function_declaration", "generator_function"):
                name_node = node.child_by_field_name("name")
                name = self.get_text(name_node)
                self.functions.append({
                    "name": name,
                    "signature": f"function {name}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": self.current_class
                })
            elif node_type == "arrow_function":
                # Arrow function can be assigned to a variable
                name = "anonymous"
                if node.parent and node.parent.type == "variable_declarator":
                    name_node = node.parent.child_by_field_name("id")
                    name = self.get_text(name_node)
                self.functions.append({
                    "name": name,
                    "signature": f"const {name} = (...) => ...",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": self.current_class
                })
            elif node_type == "method_definition":
                name_node = node.child_by_field_name("name")
                self.functions.append({
                    "name": self.get_text(name_node),
                    "signature": f"{self.get_text(name_node)}(...)",
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "enclosing_class": self.current_class
                })
            elif node_type == "class_declaration":
                name_node = node.child_by_field_name("name")
                name = self.get_text(name_node)
                self.classes.append({
                    "name": name,
                    "start_line": node.start_point[0] + 1,
                    "end_line": node.end_point[0] + 1,
                    "bases": []
                })
                prev_class = self.current_class
                self.current_class = name
                for child in node.children:
                    self.visit(child)
                self.current_class = prev_class
                return

            elif node_type == "import_statement":
                self.imports.append({
                    "raw": self.get_text(node).strip(),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type == "call_expression":
                func_node = node.child_by_field_name("function")
                self.call_sites.append({
                    "name": self.get_text(func_node),
                    "start_line": node.start_point[0] + 1
                })

            elif node_type in ("variable_declaration", "lexical_declaration") and node.parent and node.parent.type == "program":
                # Find all variables declared in program block
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            self.globals.append({
                                "name": self.get_text(name_node),
                                "start_line": node.start_point[0] + 1
                            })

        # Recurse down children if not handled by a block early-returning/skipping
        for child in node.children:
            self.visit(child)
