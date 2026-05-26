"""
Community Intelligence — HN Algolia, Reddit JSON, StackOverflow APIs (all free).
"""
from __future__ import annotations
import time
import httpx
from ocis.config import HN_ALGOLIA_URL


def _get(url: str, params: dict = None, delay: float = 0.5) -> dict | list:
    time.sleep(delay)
    try:
        r = httpx.get(url, params=params or {}, timeout=15,
                      headers={"User-Agent": "OCIS/1.0 (opensource contributor bot)"})
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}


class CommunityIntelligence:
    def gather_hn(self, project_name: str) -> list:
        data = _get(f"{HN_ALGOLIA_URL}/search",
                    {"query": project_name, "tags": "story", "hitsPerPage": 20})
        hits = data.get("hits", []) if isinstance(data, dict) else []
        results = []
        for h in hits:
            results.append({
                "title": h.get("title", ""),
                "url": h.get("url", ""),
                "score": h.get("points", 0),
                "comments": h.get("num_comments", 0),
                "created_at": h.get("created_at", ""),
                "source": "hackernews",
            })
        return results

    def gather_reddit(self, project_name: str) -> list:
        data = _get(
            "https://www.reddit.com/search.json",
            {"q": project_name, "sort": "hot", "limit": 20, "type": "link"},
        )
        posts = (data.get("data", {}).get("children", [])
                 if isinstance(data, dict) else [])
        results = []
        for p in posts:
            d = p.get("data", {})
            results.append({
                "title": d.get("title", ""),
                "text": (d.get("selftext") or "")[:400],
                "score": d.get("score", 0),
                "comments": d.get("num_comments", 0),
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "subreddit": d.get("subreddit", ""),
                "source": "reddit",
            })
        return results

    def gather_stackoverflow(self, project_name: str) -> list:
        data = _get(
            "https://api.stackexchange.com/2.3/search/advanced",
            {"q": project_name, "site": "stackoverflow",
             "sort": "votes", "pagesize": 15, "filter": "withbody"},
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        results = []
        for item in items:
            results.append({
                "title": item.get("title", ""),
                "score": item.get("score", 0),
                "answers": item.get("answer_count", 0),
                "is_answered": item.get("is_answered", False),
                "url": item.get("link", ""),
                "tags": item.get("tags", []),
                "source": "stackoverflow",
            })
        return results

    def gather_all(self, project_name: str) -> dict:
        return {
            "hackernews": self.gather_hn(project_name),
            "reddit": self.gather_reddit(project_name),
            "stackoverflow": self.gather_stackoverflow(project_name),
        }
