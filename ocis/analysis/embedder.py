"""
Codebase Embedder — chunks source files and upserts into Qdrant for RAG.
Falls back to in-memory BM25 if Qdrant is unavailable.
"""
from __future__ import annotations
import hashlib
import os
from typing import List, Dict
from ocis.config import QDRANT_HOST, QDRANT_PORT
from ocis.core.llm.client import get_llm

_CODE_EXTS = {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".rb"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "build", "dist", "vendor"}
_COLLECTION_PREFIX = "ocis_"
_DIM = 384  # all-MiniLM-L6-v2


class CodebaseEmbedder:
    CHUNK_LINES = 40
    CHUNK_OVERLAP = 5

    def __init__(self):
        self._llm = get_llm()
        self._qdrant = None
        self._mem: Dict[str, List[dict]] = {}  # fallback: collection → chunks
        self._init_qdrant()

    def _init_qdrant(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            self._qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3)
        except Exception:
            self._qdrant = None

    def _ensure_collection(self, name: str):
        if not self._qdrant:
            return
        try:
            from qdrant_client.models import Distance, VectorParams
            existing = [c.name for c in self._qdrant.get_collections().collections]
            if name not in existing:
                self._qdrant.create_collection(
                    name, vectors_config=VectorParams(size=_DIM, distance=Distance.COSINE)
                )
        except Exception:
            self._qdrant = None

    def embed_repo(self, repo_path: str, job_id: str):
        collection = f"{_COLLECTION_PREFIX}{job_id}"
        self._ensure_collection(collection)
        self._mem[collection] = []

        for root, dirs, files in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _CODE_EXTS:
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, repo_path)
                try:
                    lines = open(fpath, encoding="utf-8", errors="ignore").readlines()
                except IOError:
                    continue
                for chunk_doc in self._chunk_file(lines, rel, ext):
                    self._upsert(collection, chunk_doc)

    def _chunk_file(self, lines: list, rel_path: str, ext: str) -> list:
        chunks = []
        step = self.CHUNK_LINES - self.CHUNK_OVERLAP
        for i in range(0, len(lines), step):
            chunk_lines = lines[i: i + self.CHUNK_LINES]
            text = "".join(chunk_lines)
            if not text.strip():
                continue
            chunks.append({
                "file": rel_path,
                "start_line": i + 1,
                "end_line": i + len(chunk_lines),
                "language": ext.lstrip("."),
                "text": text[:2000],
            })
        return chunks

    def _upsert(self, collection: str, doc: dict):
        vec = self._llm.embed(doc["text"])
        uid = int(hashlib.sha256(f"{doc['file']}:{doc['start_line']}".encode()).hexdigest()[:8], 16)
        # In-memory fallback always
        self._mem.setdefault(collection, []).append({**doc, "_vec": vec, "_id": uid})
        if not self._qdrant:
            return
        try:
            from qdrant_client.models import PointStruct
            self._qdrant.upsert(collection, [PointStruct(id=uid, vector=vec, payload=doc)])
        except Exception:
            pass

    def search(self, job_id: str, query: str, top_k: int = 5) -> list:
        collection = f"{_COLLECTION_PREFIX}{job_id}"
        q_vec = self._llm.embed(query)

        if self._qdrant:
            try:
                hits = self._qdrant.search(collection, query_vector=q_vec, limit=top_k)
                return [{"file": h.payload.get("file"), "lines": f"{h.payload.get('start_line')}-{h.payload.get('end_line')}",
                         "snippet": h.payload.get("text", "")[:300], "score": h.score} for h in hits]
            except Exception:
                pass

        # BM25 fallback
        docs = self._mem.get(collection, [])
        q_tokens = set(query.lower().split())
        scored = []
        for doc in docs:
            overlap = len(q_tokens & set(doc["text"].lower().split()))
            if overlap:
                scored.append((overlap, doc))
        scored.sort(reverse=True)
        return [{"file": d["file"], "lines": f"{d['start_line']}-{d['end_line']}",
                 "snippet": d["text"][:300], "score": s / 10}
                for s, d in scored[:top_k]]
