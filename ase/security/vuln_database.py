"""
VulnDatabase — CVE/NVD enrichment for static analysis findings.

Enriches ASE findings with:
  • CVE IDs from NVD (National Vulnerability Database)
  • CVSS v3 base scores
  • Known exploit references (CISA KEV)
  • CWE descriptions
  • Affected version ranges (for dependency scanning)
"""
from __future__ import annotations
import time
import hashlib
from typing import Dict, Any, List, Optional
import requests

_NVD_API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_CISA_KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"

_CWE_DESCRIPTIONS = {
    "CWE-79": "Cross-site Scripting (XSS) — attacker injects malicious scripts into web pages",
    "CWE-89": "SQL Injection — unsanitised input alters database queries",
    "CWE-78": "OS Command Injection — unsanitised input executed as shell command",
    "CWE-22": "Path Traversal — attacker accesses files outside intended directory",
    "CWE-94": "Code Injection — attacker injects and executes arbitrary code",
    "CWE-190": "Integer Overflow — arithmetic operation wraps around max value",
    "CWE-125": "Out-of-bounds Read — memory access before/beyond buffer bounds",
    "CWE-787": "Out-of-bounds Write — memory write outside allocated buffer",
    "CWE-416": "Use After Free — memory accessed after it has been freed",
    "CWE-476": "NULL Pointer Dereference — program dereferences a null pointer",
    "CWE-119": "Buffer Overflow — classic memory corruption vulnerability",
    "CWE-400": "Uncontrolled Resource Consumption — DoS via resource exhaustion",
    "CWE-502": "Deserialization of Untrusted Data — RCE via malicious serialized objects",
    "CWE-918": "Server-Side Request Forgery (SSRF)",
    "CWE-611": "XML External Entity (XXE) injection",
    "CWE-20": "Improper Input Validation",
    "CWE-287": "Improper Authentication",
    "CWE-862": "Missing Authorization",
    "CWE-798": "Use of Hard-coded Credentials",
    "CWE-327": "Use of Broken or Risky Cryptographic Algorithm",
    "CWE-330": "Use of Insufficiently Random Values",
}


class VulnDatabase:
    def __init__(self, nvd_api_key: str = ""):
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "ASE-VulnDB/1.0"})
        if nvd_api_key:
            self._session.headers.update({"apiKey": nvd_api_key})
        self._cisa_kev_cache: Optional[set] = None

    def enrich_finding(self, finding: Dict[str, Any]) -> Dict[str, Any]:
        """
        Enrich a static analysis finding with CVE/CVSS data.
        Returns the finding dict with added 'cve_enrichment' key.
        """
        cwes = finding.get("cwe", [])
        enrichment: Dict[str, Any] = {
            "cwe_descriptions": {},
            "related_cves": [],
            "max_cvss_score": 0.0,
            "is_in_cisa_kev": False,
            "exploit_available": False,
            "recommended_priority": "medium",
        }

        # Add CWE descriptions
        for cwe in cwes:
            if cwe in _CWE_DESCRIPTIONS:
                enrichment["cwe_descriptions"][cwe] = _CWE_DESCRIPTIONS[cwe]

        # Query NVD for related CVEs (rate-limited: 1 req/6s without key)
        keyword = finding.get("rule_id", "").replace("_", " ")
        if keyword and cwes:
            cves = self._search_nvd(cwes[0], keyword)
            enrichment["related_cves"] = cves[:5]
            if cves:
                scores = [c.get("cvss_score", 0.0) for c in cves if c.get("cvss_score")]
                if scores:
                    enrichment["max_cvss_score"] = max(scores)

        # Check CISA KEV
        cve_ids = [c["cve_id"] for c in enrichment["related_cves"]]
        if cve_ids:
            kev_set = self._get_cisa_kev()
            for cve_id in cve_ids:
                if cve_id in kev_set:
                    enrichment["is_in_cisa_kev"] = True
                    enrichment["exploit_available"] = True
                    break

        # Determine priority
        cvss = enrichment["max_cvss_score"]
        if enrichment["is_in_cisa_kev"] or cvss >= 9.0:
            enrichment["recommended_priority"] = "critical"
        elif cvss >= 7.0 or enrichment["exploit_available"]:
            enrichment["recommended_priority"] = "high"
        elif cvss >= 4.0:
            enrichment["recommended_priority"] = "medium"
        else:
            enrichment["recommended_priority"] = "low"

        finding["cve_enrichment"] = enrichment
        return finding

    def _search_nvd(self, cwe_id: str, keyword: str) -> List[Dict]:
        """Search NVD for CVEs related to a CWE."""
        try:
            params = {
                "cweId": cwe_id,
                "resultsPerPage": 5,
                "startIndex": 0,
            }
            time.sleep(0.7)  # NVD rate limit (without API key: 5 req/30s)
            resp = self._session.get(_NVD_API, params=params, timeout=10)
            if resp.status_code != 200:
                return []
            data = resp.json()
            results = []
            for vuln in data.get("vulnerabilities", []):
                cve = vuln.get("cve", {})
                cve_id = cve.get("id", "")
                desc = next(
                    (d["value"] for d in cve.get("descriptions", []) if d.get("lang") == "en"),
                    "",
                )
                metrics = cve.get("metrics", {})
                cvss_score = 0.0
                for key in ("cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
                    if key in metrics and metrics[key]:
                        cvss_score = metrics[key][0].get("cvssData", {}).get("baseScore", 0.0)
                        break
                results.append({
                    "cve_id": cve_id,
                    "description": desc[:300],
                    "cvss_score": cvss_score,
                    "published": cve.get("published", ""),
                })
            return results
        except Exception:
            return []

    def _get_cisa_kev(self) -> set:
        """Fetch CISA Known Exploited Vulnerabilities catalog (cached)."""
        if self._cisa_kev_cache is not None:
            return self._cisa_kev_cache
        try:
            resp = self._session.get(_CISA_KEV, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self._cisa_kev_cache = {
                    v["cveID"] for v in data.get("vulnerabilities", [])
                }
                return self._cisa_kev_cache
        except Exception:
            pass
        self._cisa_kev_cache = set()
        return self._cisa_kev_cache

    def bulk_enrich(self, findings: List[Dict]) -> List[Dict]:
        """Enrich a list of findings. Returns enriched list sorted by priority."""
        enriched = [self.enrich_finding(f) for f in findings]
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        enriched.sort(
            key=lambda f: priority_order.get(
                f.get("cve_enrichment", {}).get("recommended_priority", "low"), 3
            )
        )
        return enriched
