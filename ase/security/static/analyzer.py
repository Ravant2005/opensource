import os
import re
import json
import hashlib
import subprocess
import socket
from typing import List, Dict, Any, Optional

# ---------------------------------------------------------------------------
# Human-readable plain-English explanations keyed by rule or CWE
# ---------------------------------------------------------------------------
_PLAIN_MAP: Dict[str, str] = {
    # OS command injection
    "CWE-78": "Your code runs shell commands using unsanitised input. An attacker can inject extra commands and take over your machine.",
    "ase.python.os-system": "Your code runs shell commands using unsanitised input. An attacker can inject extra commands and take over your machine.",
    # Code injection / eval / exec
    "CWE-94": "Your code uses eval() or exec() to run strings as code. An attacker who controls that string can run anything they want on the host.",
    "ase.python.exec-eval": "Your code uses eval() or exec() to run strings as code. An attacker who controls that string can run anything they want on the host.",
    "ase.js.eval": "Your JavaScript code uses eval(). Strings fed to eval() can run arbitrary code so this is a serious risk.",
    # Secrets / credential leakage
    "CWE-312": "A secret (AWS key, password, token) is hard-coded in your source code. Anyone with repo access can read it.",
    "ase.secret.aws-key": "An AWS access key ID was spotted in the source. Rotate it immediately and remove it from code.",
    # SQL injection
    "CWE-89": "Your code builds SQL queries by concatenating strings. An attacker can inject SQL to read or destroy your database.",
    # XSS
    "CWE-79": "User input is rendered directly in a web page without escaping. An attacker can run scripts in your users' browsers.",
    # Buffer overflow
    "CWE-120": "Your code copies data to a fixed-size buffer without checking the length. An attacker can overflow the buffer and hijack execution.",
    # Use-after-free
    "CWE-416": "Your code uses memory after it has been freed, allowing attackers to corrupt the program state.",
    # Path traversal
    "CWE-22": "Your code opens a file using a path built from user input. An attacker can use ../ to read or overwrite any file on the system.",
    # Hardcoded credential
    "CWE-798": "A username, password, or hardcoded credential was found in the code. Use environment variables or a secrets manager instead.",
    # Insecure deserialisation
    "CWE-502": "Your code deserialises data from an untrusted source. An attacker can craft a payload that runs arbitrary code when deserialised.",
    # Crypto weak algorithm
    "CWE-327": "Your code uses a broken or deprecated crypto algorithm (e.g. MD5, SHA-1, DES). An attacker can break the encryption.",
    # SSRF
    "CWE-918": "Your code makes an HTTP request using a URL that incorporates user input. An attacker can direct the server to internal services.",
    # Open redirect
    "CWE-601": "Your code redirects users to a URL built from untrusted input. An attacker can redirect them to a phishing site.",
    # Missing auth
    "CWE-861": "This endpoint or route has no access-control check. Anyone can reach it and perform actions they should not be allowed to.",
    # Insecure defaults
    "CWE-276": "Your code runs with more permission than it needs. An attacker who compromises it gains wider access to the system.",
    # Race condition
    "CWE-362": "Your code checks a condition and acts on it in two separate steps. An attacker can race to change the state between those two steps.",
}

_SEVERITY_PLAIN = {
    "CRITICAL": "This is a critical vulnerability — fix it immediately.",
    "ERROR": "This is a high-severity finding that needs fixing soon.",
    "HIGH": "This is a serious security issue that should be fixed.",
    "WARNING": "This is a moderate risk. It should be addressed before release.",
    "MEDIUM": "This is a moderate finding worth addressing.",
    "LOW": "This is a minor issue that won't cause immediate harm.",
    "INFO": "This is informational — worth knowing but low risk.",
}


def _build_plain_message(rule_id: str, message: str, cwe_list: List[str], severity: str) -> str:
    """Return a friendly plain-English explanation for a static finding."""
    for cwe in cwe_list:
        if cwe in _PLAIN_MAP:
            return _PLAIN_MAP[cwe]
    if rule_id in _PLAIN_MAP:
        return _PLAIN_MAP[rule_id]
    sev_hint = _SEVERITY_PLAIN.get(severity, "")
    body = message or rule_id
    return f"{body}. {sev_hint}".strip()


_PLAIN_BEHAVIORAL: Dict[str, str] = {
    "race_condition": "This function touches shared state but has no lock or mutex protecting it. Two threads running at the same time can corrupt data or crash the program.",
    "privilege_escalation": "This function calls a privileged operation (like setuid) without confirming the caller is authorised to do so. An attacker who triggers this path gains root-level access.",
    "unsafe_memory": "Potentially unsafe memory operations were detected: dynamic allocation (malloc) combined with bounded copy (strcpy/sprintf/gets), or a pointer that appears to be used after being freed. This is a classic memory-corruption pattern that attackers often exploit.",
}
_SEVERITY_SCORE = {"CRITICAL": 1.0, "ERROR": 0.85, "HIGH": 0.75, "WARNING": 0.5, "MEDIUM": 0.5, "LOW": 0.2, "INFO": 0.1}
_CWE_EXPLOIT_BONUS = {
    "CWE-78": 0.2,  # OS command injection
    "CWE-89": 0.2,  # SQL injection
    "CWE-79": 0.15, # XSS
    "CWE-119": 0.2, # Buffer overflow
    "CWE-416": 0.2, # Use-after-free
    "CWE-20": 0.1,  # Improper input validation
}


class UnifiedFinding:
    """Standardized schema for all static analysis findings across all tools."""
    def __init__(
        self,
        tool: str,
        rule_id: str,
        file_path: str,
        line_number: int,
        message: str,
        severity: str,
        cwe: List[str],
        cve: Optional[str] = None,
        snippet: Optional[str] = None,
    ):
        self.tool = tool
        self.rule_id = rule_id
        self.file_path = file_path
        self.line_number = line_number
        self.message = message
        self.severity = severity.upper()
        self.cwe = cwe
        self.cve = cve or ""
        self.snippet = snippet or ""
        self.exploitability_score = self._compute_exploitability()
        # Dedup key: location + rule hash
        self.dedup_key = hashlib.sha256(
            f"{file_path}:{line_number}:{rule_id}".encode()
        ).hexdigest()[:16]

    def _compute_exploitability(self) -> float:
        base = _SEVERITY_SCORE.get(self.severity, 0.1)
        bonus = max((_CWE_EXPLOIT_BONUS.get(c, 0.0) for c in self.cwe), default=0.0)
        return round(min(base + bonus, 1.0), 3)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "rule_id": self.rule_id,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "message": self.message,
            "severity": self.severity,
            "cwe": self.cwe,
            "cve": self.cve,
            "snippet": self.snippet,
            "exploitability_score": self.exploitability_score,
            "dedup_key": self.dedup_key,
            "finding_type": "vulnerability_fix",
            "plain_explanation": _build_plain_message(self.rule_id, self.message, self.cwe, self.severity),
        }


# ---------------------------------------------------------------------------
# Semgrep
# ---------------------------------------------------------------------------
class SemgrepAnalyzer:
    def __init__(self, semgrep_bin: str = "semgrep"):
        preferred = os.environ.get("ASE_SEMGREP_BIN", "")
        if preferred and os.path.exists(preferred):
            self.semgrep_bin = preferred
        elif os.path.exists("/opt/homebrew/bin/semgrep"):
            self.semgrep_bin = "/opt/homebrew/bin/semgrep"
        else:
            self.semgrep_bin = semgrep_bin

    def _semgrep_env(self, repo_path: str) -> Dict[str, str]:
        env = os.environ.copy()
        semgrep_home = os.path.join(repo_path, ".ase_semgrep_home")
        os.makedirs(semgrep_home, exist_ok=True)
        env["HOME"] = semgrep_home
        cert_file = "/opt/homebrew/etc/ca-certificates/cert.pem"
        if os.path.exists(cert_file):
            env.setdefault("SSL_CERT_FILE", cert_file)
            env.setdefault("X509_CERT_FILE", cert_file)
        return env

    def scan(self, repo_path: str, config_path: str = "auto") -> List[UnifiedFinding]:
        if not self.is_available():
            return []

        # Try real scan first
        cmd = [self.semgrep_bin, "scan", "--config", config_path, "--json", repo_path]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=300, # Increased timeout for large repos
                env=self._semgrep_env(repo_path),
            )
            
            # If semgrep returned findings (exit 0 or 1)
            if res.returncode in (0, 1) and res.stdout.strip():
                return self.parse_json(res.stdout)
            
            # If semgrep failed because of registry/network
            if "registry" in res.stderr.lower() or "unreachable" in res.stderr.lower():
                print("Semgrep registry unreachable. Using local fallback rules for coverage.")
                return self._scan_with_fallback_rules(repo_path)
            
            # General failure
            if res.returncode not in (0, 1):
                print(f"Semgrep CLI Error: {res.stderr}")
                return self._scan_with_fallback_rules(repo_path)
                
        except subprocess.TimeoutExpired:
            print("Semgrep scan timed out. Falling back to local rules.")
            return self._scan_with_fallback_rules(repo_path)
        except Exception as e:
            print(f"Semgrep scan failed: {e}")
            return self._scan_with_fallback_rules(repo_path)

        return []

    def is_available(self) -> bool:
        return bool(shutil.which(self.semgrep_bin) or os.path.exists(self.semgrep_bin))

    def _scan_with_fallback_rules(self, repo_path: str) -> List[UnifiedFinding]:
        fallback_rules = """rules:
  - id: ase.python.os-system
    languages: [python]
    severity: ERROR
    message: Potential command execution via os.system
    patterns:
      - pattern: os.system($X)
    metadata:
      cwe: ["CWE-78"]
  - id: ase.python.exec-eval
    languages: [python]
    severity: WARNING
    message: Dynamic execution via eval/exec
    pattern-either:
      - pattern: eval($X)
      - pattern: exec($X)
    metadata:
      cwe: ["CWE-94"]
  - id: ase.js.eval
    languages: [javascript, typescript]
    severity: WARNING
    message: Dynamic execution via eval
    pattern: eval($X)
    metadata:
      cwe: ["CWE-94"]
  - id: ase.secret.aws-key
    languages: [python, javascript, typescript, go, java, c, cpp, rust]
    severity: ERROR
    message: Possible AWS access key in source code
    patterns:
      - pattern-regex: "(AKIA|ASIA)[A-Z0-9]{16}"
    metadata:
      cwe: ["CWE-312"]
"""
        rule_file = os.path.join(repo_path, ".ase_semgrep_fallback.yml")
        try:
            with open(rule_file, "w", encoding="utf-8") as f:
                f.write(fallback_rules)
        except IOError:
            return []

        cmd = [self.semgrep_bin, "scan", "--config", rule_file, "--json", repo_path]
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=900,
                env=self._semgrep_env(repo_path),
            )
            if res.returncode not in (0, 1):
                print(f"Semgrep fallback warning: {res.stderr}")
                return []
            return self.parse_json(res.stdout)
        except Exception:
            return []

    def parse_json(self, json_str: str) -> List[UnifiedFinding]:
        if not json_str.strip():
            return []
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        findings = []
        for match in data.get("results", []):
            rule_id = match.get("check_id", "unknown")
            file_path = match.get("path", "")
            start_point = match.get("start", {})
            line_number = start_point.get("line", 1)
            extra = match.get("extra", {})
            message = extra.get("message", "")
            severity = extra.get("severity", "WARNING")
            metadata = extra.get("metadata", {})
            cwe_raw = metadata.get("cwe", [])
            cwe_list = [cwe_raw] if isinstance(cwe_raw, str) else cwe_raw
            cleaned_cwes = []
            for c in cwe_list:
                m = re.search(r"CWE-\d+", c, re.IGNORECASE)
                if m:
                    cleaned_cwes.append(m.group(0).upper())
            findings.append(UnifiedFinding(
                tool="semgrep", rule_id=rule_id, file_path=file_path,
                line_number=line_number, message=message, severity=severity,
                cwe=cleaned_cwes,
            ))
        return findings


# ---------------------------------------------------------------------------
# CodeQL
# ---------------------------------------------------------------------------
class CodeQLAnalyzer:
    def __init__(self, codeql_bin: str = "codeql"):
        self.codeql_bin = codeql_bin

    def create_database(self, repo_path: str, db_path: str, language: str) -> bool:
        cmd = [self.codeql_bin, "database", "create", db_path,
               f"--source-root={repo_path}", f"--language={language}", "--overwrite"]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=False).returncode == 0
        except FileNotFoundError:
            return False

    def analyze_database(self, db_path: str, queries_path: str, sarif_output: str) -> bool:
        cmd = [self.codeql_bin, "database", "analyze", db_path, queries_path,
               "--format=sarif-latest", f"--output={sarif_output}"]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=False).returncode == 0
        except FileNotFoundError:
            return False

    def parse_sarif(self, sarif_path: str) -> List[UnifiedFinding]:
        if not os.path.exists(sarif_path):
            return []
        try:
            with open(sarif_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return []

        findings = []
        for run in data.get("runs", []):
            rules_map = {r["id"]: r for r in run.get("tool", {}).get("driver", {}).get("rules", [])}
            for res in run.get("results", []):
                rule_id = res.get("ruleId", "unknown")
                message = res.get("message", {}).get("text", "")
                file_path, line_number = "", 1
                locations = res.get("locations", [])
                if locations:
                    phys = locations[0].get("physicalLocation", {})
                    file_path = phys.get("artifactLocation", {}).get("uri", "")
                    line_number = phys.get("region", {}).get("startLine", 1)
                rule_meta = rules_map.get(rule_id, {})
                tags = rule_meta.get("properties", {}).get("tags", [])
                cleaned_cwes = list({
                    f"CWE-{int(t.split('cwe-')[-1])}" if "external/cwe/cwe-" in t
                    else t.upper()
                    for t in tags
                    if "external/cwe/cwe-" in t or t.upper().startswith("CWE-")
                })
                level = rule_meta.get("defaultConfiguration", {}).get("level", "warning").upper()
                severity = "ERROR" if "ERROR" in level else ("WARNING" if "WARNING" in level else "INFO")
                findings.append(UnifiedFinding(
                    tool="codeql", rule_id=rule_id, file_path=file_path,
                    line_number=line_number, message=message, severity=severity,
                    cwe=cleaned_cwes,
                ))
        return findings


# ---------------------------------------------------------------------------
# Gitleaks - secrets detection
# ---------------------------------------------------------------------------
class GitleaksAnalyzer:
    def __init__(self, gitleaks_bin: str = "gitleaks"):
        preferred = os.environ.get("ASE_GITLEAKS_BIN", "")
        if preferred and os.path.exists(preferred):
            self.gitleaks_bin = preferred
        elif os.path.exists("/opt/homebrew/bin/gitleaks"):
            self.gitleaks_bin = "/opt/homebrew/bin/gitleaks"
        else:
            self.gitleaks_bin = gitleaks_bin

    def scan(self, repo_path: str) -> List[UnifiedFinding]:
        cmd = [self.gitleaks_bin, "detect", "--source", repo_path,
               "--report-format", "json", "--report-path", "-", "--no-git"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=900)
            # Gitleaks exit code 1 means leaks found; 0 means clean
            if res.returncode not in (0, 1):
                print(f"Gitleaks CLI Warning: {res.stderr}")
                return []
            return self.parse_json(res.stdout)
        except subprocess.TimeoutExpired:
            print("Gitleaks scan timed out after 900s.")
            return []
        except FileNotFoundError:
            print("Gitleaks binary not found. Skipping secrets scan.")
            return []

    def parse_json(self, json_str: str) -> List[UnifiedFinding]:
        if not json_str.strip():
            return []
        try:
            leaks = json.loads(json_str)
        except json.JSONDecodeError:
            return []
        if not isinstance(leaks, list):
            return []
        findings = []
        for leak in leaks:
            rule_id = leak.get("RuleID", leak.get("ruleID", "gitleaks.secret"))
            file_path = leak.get("File", leak.get("file", ""))
            line_number = leak.get("StartLine", leak.get("startLine", 1))
            message = f"Secret leaked: {leak.get('Description', leak.get('description', rule_id))}"
            secret_preview = leak.get("Secret", leak.get("secret", ""))[:8] + "..."
            findings.append(UnifiedFinding(
                tool="gitleaks", rule_id=rule_id, file_path=file_path,
                line_number=line_number, message=message, severity="ERROR",
                cwe=["CWE-312"],  # Cleartext storage of sensitive information
                snippet=secret_preview,
            ))
        return findings


# ---------------------------------------------------------------------------
# Trivy - dependency CVE scanner
# ---------------------------------------------------------------------------
class TrivyAnalyzer:
    def __init__(self, trivy_bin: str = "trivy"):
        preferred = os.environ.get("ASE_TRIVY_BIN", "")
        if preferred and os.path.exists(preferred):
            self.trivy_bin = preferred
        elif os.path.exists("/opt/homebrew/bin/trivy"):
            self.trivy_bin = "/opt/homebrew/bin/trivy"
        else:
            self.trivy_bin = trivy_bin

    def scan(self, repo_path: str) -> List[UnifiedFinding]:
        # Try full scan first
        cmd = [
            self.trivy_bin,
            "fs",
            "--format",
            "json",
            "--quiet",
            repo_path,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=600)
            if res.returncode == 0:
                return self.parse_json(res.stdout)
            
            # Fallback to offline scan if network is down or rate-limited
            print("Trivy full scan failed, attempting offline scan.")
            offline_cmd = cmd + ["--offline-scan", "--skip-db-update"]
            res = subprocess.run(offline_cmd, capture_output=True, text=True, check=False, timeout=300)
            if res.returncode == 0:
                return self.parse_json(res.stdout)
                
            print(f"Trivy CLI Warning: {res.stderr}")
            return []
        except subprocess.TimeoutExpired:
            print("Trivy scan timed out.")
            return []
        except Exception as e:
            print(f"Trivy scan error: {e}")
            return []

    def parse_json(self, json_str: str) -> List[UnifiedFinding]:
        if not json_str.strip():
            return []
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []

        findings = []
        for result in data.get("Results", []):
            target_file = result.get("Target", "")
            for vuln in result.get("Vulnerabilities", []):
                cve_id = vuln.get("VulnerabilityID", "")
                pkg_name = vuln.get("PkgName", "")
                installed_ver = vuln.get("InstalledVersion", "")
                fixed_ver = vuln.get("FixedVersion", "N/A")
                severity = vuln.get("Severity", "UNKNOWN")
                description = vuln.get("Description", "")[:200]
                message = (
                    f"{cve_id} in {pkg_name} {installed_ver} "
                    f"(fix: {fixed_ver}): {description}"
                )
                cwes = [f"CWE-{c}" for c in vuln.get("CweIDs", [])]
                findings.append(UnifiedFinding(
                    tool="trivy", rule_id=cve_id or "trivy.vuln",
                    file_path=target_file, line_number=1,
                    message=message, severity=severity, cwe=cwes,
                    cve=cve_id,
                ))
        return findings


# ---------------------------------------------------------------------------
# StaticAnalysisOrchestrator - master coordinator
# ---------------------------------------------------------------------------
class StaticAnalysisOrchestrator:
    """
    Runs all static analysis tools (Semgrep, CodeQL, Gitleaks, Trivy),
    merges findings, deduplicates by location+rule hash, and returns a
    ranked list sorted by exploitability score.
    """
    def __init__(self):
        self.semgrep = SemgrepAnalyzer()
        self.gitleaks = GitleaksAnalyzer()
        self.trivy = TrivyAnalyzer()
        # CodeQL is invoked separately due to its multi-step database workflow

    def run(self, repo_path: str, semgrep_config: str = "auto") -> List[UnifiedFinding]:
        all_findings: List[UnifiedFinding] = []
        all_findings.extend(self.semgrep.scan(repo_path, config_path=semgrep_config))
        all_findings.extend(self.gitleaks.scan(repo_path))
        all_findings.extend(self.trivy.scan(repo_path))

        # Deduplicate by dedup_key
        seen: set = set()
        deduped = []
        for f in all_findings:
            if f.dedup_key not in seen:
                seen.add(f.dedup_key)
                deduped.append(f)

        # Sort descending by exploitability score
        deduped.sort(key=lambda f: f.exploitability_score, reverse=True)
        return deduped
