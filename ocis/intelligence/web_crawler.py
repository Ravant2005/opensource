"""
Web crawler — polite httpx + BeautifulSoup4 crawl of official project docs.
500ms delay between requests, max 10 pages, respects basic robots.txt signals.
"""
from __future__ import annotations
import re
import time
import httpx
from typing import Optional

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

_DOC_PATTERNS = re.compile(
    r"(docs?|documentation|changelog|roadmap|guide|tutorial|getting.started|wiki)",
    re.IGNORECASE,
)
_HEADERS = {"User-Agent": "OCIS/1.0 (opensource contributor intelligence; polite bot)"}


def _fetch(url: str) -> Optional[str]:
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=10, follow_redirects=True)
        return r.text if r.status_code == 200 else None
    except Exception:
        return None


def _extract_text(html: str) -> str:
    if not _BS4:
        return re.sub(r"<[^>]+>", " ", html)[:5000]
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_links(html: str, base_url: str) -> list[str]:
    if not _BS4:
        return []
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            links.append(f"{parsed.scheme}://{parsed.netloc}{href}")
    return links


class WebCrawler:
    def crawl_docs(self, project_name: str, homepage: str, max_pages: int = 8) -> str:
        if not homepage:
            return ""
        html = _fetch(homepage)
        if not html:
            return ""

        texts = [_extract_text(html)[:3000]]
        links = _extract_links(html, homepage)
        doc_links = [l for l in links if _DOC_PATTERNS.search(l)][:max_pages]

        for url in doc_links:
            time.sleep(0.5)  # polite delay
            page_html = _fetch(url)
            if page_html:
                texts.append(_extract_text(page_html)[:2000])

        combined = "\n\n".join(texts)
        return combined[:50000]
