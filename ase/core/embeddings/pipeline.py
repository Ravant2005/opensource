"""
Code embedding + query pipeline.

This module exposes:
1) `CodeEmbeddingPipeline`: runtime pipeline used by API/RAG wrappers.
2) `CodeRAGQuery`: compatibility class used by tests and higher-level agents.
"""
from __future__ import annotations
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from ase.config import QDRANT_HOST, QDRANT_PORT

_COLLECTION = "ase_code"


@dataclass
class CodeNode:
    text: str
    metadata: Dict[str, Any]
    embedding: List[float]


def _tokenize(text: str) -> List[str]:
    return [t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if t]


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    va = a[:n]
    vb = b[:n]
    dot = sum(x * y for x, y in zip(va, vb))
    na = math.sqrt(sum(x * x for x in va))
    nb = math.sqrt(sum(y * y for y in vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class CodeEmbeddingPipeline:
    def __init__(self):
        self._model = None
        self._qdrant = None
        self._bm25_docs: List[Dict[str, Any]] = []
        self._init_model()
        self._init_qdrant()

    def _init_model(self):
        try:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
        except Exception:
            self._model = None

    def _init_qdrant(self):
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
            self._qdrant = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, timeout=3)
            dim = 384  # bge-small
            existing = [c.name for c in self._qdrant.get_collections().collections]
            if _COLLECTION not in existing:
                self._qdrant.create_collection(
                    _COLLECTION,
                    vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
                )
        except Exception:
            self._qdrant = None

    def index_functions(self, file_map: Dict[str, List[Dict[str, Any]]]):
        """Embed and store extracted function chunks."""
        for file_path, items in file_map.items():
            for item in items:
                if item.get("type") != "function":
                    continue
                text = f"{file_path}\n{item.get('name','')}\n{item.get('snippet','')}"
                doc = {
                    "file": file_path,
                    "name": item.get("name", ""),
                    "line": item.get("start_line", 1),
                    "text": text,
                }
                self._bm25_docs.append(doc)
                if self._model and self._qdrant:
                    self._upsert(doc, text)

    def _upsert(self, doc: Dict[str, Any], text: str):
        try:
            from qdrant_client.models import PointStruct
            vec = self._model.encode(text).tolist()
            uid = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            self._qdrant.upsert(_COLLECTION, [PointStruct(id=uid, vector=vec, payload=doc)])
        except Exception:
            pass

    def find_similar_functions(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self._model and self._qdrant:
            try:
                vec = self._model.encode(query).tolist()
                hits = self._qdrant.search(_COLLECTION, query_vector=vec, limit=top_k)
                return [h.payload for h in hits]
            except Exception:
                pass

        query_tokens = set(_tokenize(query))
        scored = []
        for doc in self._bm25_docs:
            overlap = len(query_tokens & set(_tokenize(doc["text"])))
            if overlap > 0:
                scored.append((float(overlap), doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:top_k]]

    def find_historical_fixes(self, vuln_description: str, top_k: int = 3) -> List[Dict[str, Any]]:
        return self.find_similar_functions(vuln_description, top_k)


class CodeRAGQuery:
    """
    Function-level retrieval over parsed staging JSON + source snippets.
    Supports dense (embedding) + sparse (keyword) hybrid scoring.
    """

    def __init__(
        self,
        staging_dir: Optional[str] = None,
        src_repo_dir: Optional[str] = None,
        embed_model: Optional[Callable[[str], List[float]]] = None,
    ):
        self.staging_dir = Path(staging_dir) if staging_dir else None
        self.src_repo_dir = Path(src_repo_dir) if src_repo_dir else None
        self.embed_model = embed_model or self._default_embed_model()
        self.nodes: List[CodeNode] = []
        self._load_nodes()

    def _default_embed_model(self) -> Callable[[str], List[float]]:
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            return lambda text: model.encode(text).tolist()
        except Exception:
            # Lightweight deterministic fallback for local/dev mode.
            return self._fallback_embed

    def _fallback_embed(self, text: str, dimension: int = 256) -> List[float]:
        vec = [0.0] * dimension
        if not text:
            return vec
        for token in _tokenize(text):
            idx = hash(token) % dimension
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _load_nodes(self):
        if not self.staging_dir or not self.staging_dir.exists():
            return
        for summary_file in sorted(self.staging_dir.glob("*.json")):
            try:
                summary = json.loads(summary_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            file_path = summary.get("file_path", "")
            language = summary.get("language", "unknown")
            source_lines = self._read_source_lines(file_path)

            for fn in summary.get("functions", []):
                start = int(fn.get("start_line", 1))
                end = int(fn.get("end_line", start))
                snippet = self._snippet_from_lines(source_lines, start, end)
                text = (
                    f"file: {file_path}\n"
                    f"language: {language}\n"
                    f"name: {fn.get('name','')}\n"
                    f"signature: {fn.get('signature','')}\n"
                    f"code:\n{snippet}"
                )
                metadata = {
                    "name": fn.get("name", ""),
                    "signature": fn.get("signature", ""),
                    "file_path": file_path,
                    "language": language,
                    "start_line": start,
                    "end_line": end,
                }
                embedding = self.embed_model(text)
                self.nodes.append(CodeNode(text=text, metadata=metadata, embedding=embedding))

    def _read_source_lines(self, relative_file: str) -> List[str]:
        if not self.src_repo_dir:
            return []
        path = self.src_repo_dir / relative_file
        if not path.exists():
            return []
        try:
            return path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return []

    def _snippet_from_lines(self, lines: List[str], start: int, end: int) -> str:
        if not lines:
            return ""
        s = max(start - 1, 0)
        e = min(end, len(lines))
        return "\n".join(lines[s:e])

    def _hybrid_search(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if not self.nodes:
            return []
        qvec = self.embed_model(query)
        qtokens = set(_tokenize(query))
        results: List[Dict[str, Any]] = []
        for node in self.nodes:
            dense = _cosine(qvec, node.embedding)
            sparse = 0.0
            if qtokens:
                ntokens = set(_tokenize(node.text))
                sparse = len(qtokens & ntokens) / max(len(qtokens), 1)
            score = round(0.7 * dense + 0.3 * sparse, 6)
            results.append({"text": node.text, "metadata": node.metadata, "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def find_similar_functions(self, func_signature: str, top_k: int = 5) -> List[Dict[str, Any]]:
        return self._hybrid_search(func_signature, top_k)

    def find_sink_patterns(self, data_type: str, top_k: int = 5) -> List[Dict[str, Any]]:
        query = f"sink vulnerable unsafe security pattern {data_type}"
        return self._hybrid_search(query, top_k)

    def find_historical_fixes(self, vuln_type: str, top_k: int = 3) -> List[Dict[str, Any]]:
        query = f"security fix mitigation patch {vuln_type}"
        return self._hybrid_search(query, top_k)
