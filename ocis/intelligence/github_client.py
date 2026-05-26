"""
GitHub Intelligence — scrapes everything public from a repo using the free REST + GraphQL API.
"""
from __future__ import annotations
import time
from typing import Optional
import httpx
from ocis.config import GITHUB_TOKEN, GITHUB_API_BASE

def _get_headers() -> dict:
    from ocis.config import GITHUB_TOKEN as _tok
    h = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _tok:
        h["Authorization"] = f"Bearer {_tok}"
    return h

_ROADMAP_PATHS = [
    "ROADMAP.md", "roadmap.md", "docs/ROADMAP.md", "docs/roadmap.md",
    ".github/ROADMAP.md", "CHANGELOG.md", "TODO.md",
]


def _gh(path: str, params: dict = None) -> dict | list:
    url = f"{GITHUB_API_BASE}{path}"
    try:
        r = httpx.get(url, headers=_get_headers(), params=params or {}, timeout=20)
        if r.status_code == 403:
            time.sleep(60)
            r = httpx.get(url, headers=_get_headers(), params=params or {}, timeout=20)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


def _gh_paginate(path: str, max_items: int = 100) -> list:
    results, page = [], 1
    while len(results) < max_items:
        batch = _gh(path, {"per_page": 100, "page": page})
        if not isinstance(batch, list) or not batch:
            break
        results.extend(batch)
        page += 1
        if len(batch) < 100:
            break
    return results[:max_items]


def _fetch_file(slug: str, path: str) -> str:
    data = _gh(f"/repos/{slug}/contents/{path}")
    if isinstance(data, dict) and data.get("encoding") == "base64":
        import base64
        try:
            return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")[:8000]
        except Exception:
            pass
    return ""


def _graphql(query: str) -> dict:
    if not GITHUB_TOKEN:
        return {}
    try:
        r = httpx.post(
            "https://api.github.com/graphql",
            headers=_get_headers(),
            json={"query": query},
            timeout=20,
        )
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


class GitHubIntelligence:
    def gather(self, repo_slug: str) -> dict:
        meta = _gh(f"/repos/{repo_slug}")
        issues = _gh_paginate(f"/repos/{repo_slug}/issues", 80)
        open_issues = [i for i in issues if not i.get("pull_request")]

        good_first = [i for i in open_issues
                      if any(l.get("name", "").lower() in ("good first issue", "good-first-issue")
                             for l in i.get("labels", []))]
        help_wanted = [i for i in open_issues
                       if any(l.get("name", "").lower() in ("help wanted", "help-wanted")
                              for l in i.get("labels", []))]

        roadmap = ""
        for rp in _ROADMAP_PATHS:
            roadmap = _fetch_file(repo_slug, rp)
            if roadmap:
                break

        discussions = self._get_discussions(repo_slug)

        return {
            "metadata": {
                "name": meta.get("name", ""),
                "full_name": meta.get("full_name", ""),
                "description": meta.get("description", ""),
                "stars": meta.get("stargazers_count", 0),
                "forks": meta.get("forks_count", 0),
                "open_issues_count": meta.get("open_issues_count", 0),
                "language": meta.get("language", ""),
                "topics": meta.get("topics", []),
                "homepage": meta.get("homepage", ""),
                "license": (meta.get("license") or {}).get("spdx_id", ""),
                "created_at": meta.get("created_at", ""),
                "pushed_at": meta.get("pushed_at", ""),
            },
            "issues": [self._slim_issue(i) for i in open_issues[:60]],
            "good_first_issues": [self._slim_issue(i) for i in good_first[:20]],
            "help_wanted": [self._slim_issue(i) for i in help_wanted[:20]],
            "labels": [l.get("name") for l in _gh(f"/repos/{repo_slug}/labels") if isinstance(l, dict)],
            "releases": _gh_paginate(f"/repos/{repo_slug}/releases", 5),
            "readme": _fetch_file(repo_slug, "README.md"),
            "contributing": _fetch_file(repo_slug, "CONTRIBUTING.md"),
            "roadmap": roadmap,
            "discussions": discussions,
        }

    def _slim_issue(self, i: dict) -> dict:
        return {
            "number": i.get("number"),
            "title": i.get("title", ""),
            "body": (i.get("body") or "")[:600],
            "labels": [l.get("name") for l in i.get("labels", [])],
            "comments": i.get("comments", 0),
            "reactions": (i.get("reactions") or {}).get("total_count", 0),
            "url": i.get("html_url", ""),
            "created_at": i.get("created_at", ""),
        }

    def _get_discussions(self, slug: str) -> list:
        owner, repo = slug.split("/", 1)
        query = f"""
        {{
          repository(owner: "{owner}", name: "{repo}") {{
            discussions(first: 20, orderBy: {{field: UPDATED_AT, direction: DESC}}) {{
              nodes {{
                title
                body
                upvoteCount
                url
                category {{ name }}
              }}
            }}
          }}
        }}
        """
        data = _graphql(query)
        nodes = (data.get("data", {}).get("repository", {})
                 .get("discussions", {}).get("nodes", []))
        return [{"title": n.get("title"), "body": (n.get("body") or "")[:400],
                 "upvotes": n.get("upvoteCount", 0), "url": n.get("url")}
                for n in nodes]
