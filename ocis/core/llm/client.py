"""
OCIS LLM Client — OpenRouter wrapper with free model rotation.
Falls back through FREE_MODELS on 429/error with exponential backoff.
Caches responses in SQLite to avoid redundant API calls.
"""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
from typing import Optional
import httpx
from ocis.config import (
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, FREE_MODELS,
    OPENROUTER_MODEL, GITHUB_USERNAME, DATABASE_URL,
)

_CACHE_DB = "ocis_llm_cache.db"
_EMBED_MODEL = None  # lazy-loaded


def _get_cache_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_CACHE_DB)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache "
        "(key TEXT PRIMARY KEY, response TEXT, model TEXT, ts TEXT)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_usage "
        "(id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, prompt_hash TEXT, "
        "tokens_est INTEGER, ts TEXT DEFAULT (datetime('now')))"
    )
    conn.commit()
    return conn


def _cache_key(messages: list, model: str) -> str:
    raw = json.dumps(messages, sort_keys=True) + model
    return hashlib.sha256(raw.encode()).hexdigest()


class OCISLLMClient:
    def __init__(self):
        self._headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": f"https://github.com/{GITHUB_USERNAME}/ocis",
            "X-Title": "OCIS",
            "Content-Type": "application/json",
        }

    def chat(self, messages: list[dict], model: str = None,
             system: str = None, temperature: float = 0.2) -> str:
        if system:
            messages = [{"role": "system", "content": system}] + list(messages)
        model = model or OPENROUTER_MODEL

        # Cache check
        key = _cache_key(messages, model)
        try:
            db = _get_cache_db()
            row = db.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
            if row:
                return row[0]
        except Exception:
            db = None

        # Try each free model with backoff
        models_to_try = [model] + [m for m in FREE_MODELS if m != model]
        last_error = ""
        for m in models_to_try:
            for attempt in range(3):
                try:
                    resp = httpx.post(
                        f"{OPENROUTER_BASE_URL}/chat/completions",
                        headers=self._headers,
                        json={"model": m, "messages": messages, "temperature": temperature},
                        timeout=60,
                    )
                    if resp.status_code == 429:
                        time.sleep(2 ** attempt)
                        continue
                    if resp.status_code != 200:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        break
                    text = resp.json()["choices"][0]["message"]["content"]
                    # Cache it
                    if db:
                        try:
                            db.execute(
                                "INSERT OR REPLACE INTO llm_cache (key, response, model, ts) "
                                "VALUES (?, ?, ?, datetime('now'))",
                                (key, text, m),
                            )
                            db.execute(
                                "INSERT INTO llm_usage (model, prompt_hash, tokens_est) VALUES (?,?,?)",
                                (m, key[:16], len(str(messages)) // 4),
                            )
                            db.commit()
                        except Exception:
                            pass
                    return text
                except Exception as e:
                    last_error = str(e)
                    time.sleep(2 ** attempt)
            # model exhausted, try next
        return f"[LLM unavailable: {last_error}]"

    def chat_json(self, messages: list[dict], system: str = None,
                  schema_hint: str = "") -> dict:
        sys_prompt = (
            (system or "") +
            "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown fences, no explanation."
        )
        if schema_hint:
            sys_prompt += f"\n\nExpected schema hint:\n{schema_hint}"
        raw = self.chat(messages, system=sys_prompt, temperature=0.1)
        return _extract_json(raw)

    def embed(self, text: str) -> list[float]:
        global _EMBED_MODEL
        if _EMBED_MODEL is None:
            try:
                from sentence_transformers import SentenceTransformer
                _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
            except Exception:
                return [0.0] * 384
        try:
            return _EMBED_MODEL.encode(text).tolist()
        except Exception:
            return [0.0] * 384


def _extract_json(text: str) -> dict | list:
    """Robustly extract JSON from LLM output (supports objects and lists)."""
    if not text or "[LLM unavailable" in text:
        return {"error": "llm_unavailable", "raw": text}

    # Strip markdown fences
    clean_text = re.sub(r"```(?:json)?\s*", "", text).strip().rstrip("`").strip()
    
    # Try direct parse
    try:
        return json.loads(clean_text)
    except Exception:
        pass

    # Try finding the first/largest { } or [ ] block
    # We use non-greedy matching first, then fallback to greedy if it fails
    # This handles cases with multiple blocks or leading/trailing text
    for pattern in [r"\{.*\}", r"\[.*\]"]:
        match = re.search(pattern, text, re.DOTALL)
        if match:
            candidate = match.group(0)
            try:
                return json.loads(candidate)
            except Exception:
                # If greedy fails, try non-greedy (first block)
                non_greedy_pattern = pattern.replace(".*", ".*?")
                match = re.search(non_greedy_pattern, text, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group(0))
                    except Exception:
                        pass
    
    return {"error": "json_parse_failed", "raw": text[:500]}


# Singleton
_client: Optional[OCISLLMClient] = None


def get_llm() -> OCISLLMClient:
    global _client
    if _client is None:
        _client = OCISLLMClient()
    return _client
