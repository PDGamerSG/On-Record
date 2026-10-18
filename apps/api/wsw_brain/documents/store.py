"""Documents in the meeting graph: (:Document)-[:HAS_CHUNK]->(:DocChunk), searchable like utterances.

DocChunk nodes get their own full-text and vector indexes, so document search never mixes with the
Utterance indexes or their dimension check. Values always travel as $params.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

from ..graph import GraphQueryError, GraphStore
from ..graph.text import fulltext_query, query_terms
from .split import Chunk

log = logging.getLogger(__name__)

SCAN_LIMIT = 5000  # chunks examined by the substring search for words in Indian scripts
# Words in any non-Latin script. The full-text query keeps only ASCII terms, so Hindi, Kannada or Tamil
# words in a question would otherwise never match document text.
_TOKEN = re.compile(r"[^\s.,;:!?\"'()\[\]{}<>/\\|\u0964\u0965\-]+")

SCHEMA = [
    "CREATE INDEX FOR (d:Document) ON (d.id)",
    "CREATE INDEX FOR (c:DocChunk) ON (c.id)",
    "CREATE INDEX FOR (c:DocChunk) ON (c.doc_id)",
    "CREATE FULLTEXT INDEX FOR (c:DocChunk) ON (c.text)",
]


def _vector_index(dim: int) -> str:
    return (
        "CREATE VECTOR INDEX FOR (c:DocChunk) ON (c.embedding) "
        f"OPTIONS {{dimension: {int(dim)}, similarityFunction: 'cosine'}}"
    )


UPSERT_DOCUMENT = """
MERGE (d:Document {id: $id})
SET d.title = $title, d.filename = $filename, d.language = $language, d.pages = $pages, d.parts = $parts,
    d.bytes = $bytes, d.created_at = $created_at, d.status = $status, d.embedder = $embedder,
    d.digitised_by = $digitised_by
"""

SET_DOCUMENT_SUMMARY = "MATCH (d:Document {id: $id}) SET d.summary = $summary, d.summary_model = $model"

DELETE_CHUNKS = "MATCH (c:DocChunk {doc_id: $id}) DETACH DELETE c"

# FOREACH ... CASE sets the embedding only when there is one (see write_utterances in graph/cypher.py).
WRITE_CHUNKS = """
UNWIND $rows AS r
CREATE (c:DocChunk {id: r.id, doc_id: r.doc_id, seq: r.seq, page_start: r.page_start, page_end: r.page_end,
                    heading: r.heading, text: r.text})
FOREACH (e IN CASE WHEN r.embedding IS NULL THEN [] ELSE [r.embedding] END | SET c.embedding = vecf32(e))
WITH c, r
MATCH (d:Document {id: r.doc_id})
CREATE (d)-[:HAS_CHUNK]->(c)
"""

_DOCUMENT_FIELDS = """
d.id AS id, d.title AS title, d.filename AS filename, d.language AS language, d.pages AS pages,
d.parts AS parts, d.bytes AS bytes, d.created_at AS created_at, d.status AS status, d.summary AS summary,
d.summary_model AS summary_model, d.embedder AS embedder, d.digitised_by AS digitised_by
"""

LIST_DOCUMENTS = f"""
MATCH (d:Document)
WITH d
OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocChunk)
WITH d, count(c) AS chunk_count
RETURN {_DOCUMENT_FIELDS}, chunk_count
ORDER BY created_at DESC
"""

ONE_DOCUMENT = f"""
MATCH (d:Document {{id: $id}})
WITH d
OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocChunk)
WITH d, count(c) AS chunk_count
RETURN {_DOCUMENT_FIELDS}, chunk_count
"""

DOCUMENT_CHUNKS = """
MATCH (c:DocChunk {doc_id: $id})
RETURN c.id AS id, c.seq AS seq, c.page_start AS page_start, c.page_end AS page_end, c.heading AS heading,
       c.text AS text
ORDER BY seq
"""

DELETE_DOCUMENT = """
MATCH (d:Document {id: $id})
WITH d, d.id AS id
DETACH DELETE d
RETURN count(id) AS deleted
"""

MEETING_STARTS = "MATCH (m:Meeting) WHERE m.id IN $ids RETURN m.id AS id, m.started_at AS started_at"

_HIT_TAIL = """
WITH c, score
MATCH (d:Document {id: c.doc_id})
RETURN c.id AS id, c.doc_id AS doc_id, d.title AS doc_title, c.seq AS seq, c.page_start AS page_start,
       c.page_end AS page_end, c.heading AS heading, c.text AS text, score
"""


def _scope(by_doc: bool) -> str:
    return "WHERE c.doc_id = $doc_id\n" if by_doc else ""


def fulltext_chunks(by_doc: bool) -> str:
    return (
        "CALL db.idx.fulltext.queryNodes('DocChunk', $query) YIELD node, score\n"
        "WITH node AS c, score\n"
        f"{_scope(by_doc)}"
        "WITH c, score ORDER BY score DESC LIMIT $k" + _HIT_TAIL
    )


def scan_chunks(by_doc: bool) -> str:
    """Substring match for words the full-text index cannot query (non-Latin scripts)."""
    match = "MATCH (c:DocChunk {doc_id: $doc_id})" if by_doc else "MATCH (c:DocChunk)"
    return (
        f"{match}\n"
        "WITH c LIMIT $scan_limit\n"
        "WITH c, size([t IN $terms WHERE c.text CONTAINS t]) AS matched\n"
        "WHERE matched > 0\n"
        "WITH c, toFloat(matched) AS score ORDER BY score DESC LIMIT $k" + _HIT_TAIL
    )


def native_terms(query: str) -> list[str]:
    """Distinct words of two or more characters that contain non-ASCII letters."""
    terms: list[str] = []
    for token in _TOKEN.findall(query or ""):
        if len(token) >= 2 and not token.isascii() and token not in terms:
            terms.append(token)
    return terms[:12]


def vector_chunks(by_doc: bool) -> str:
    return (
        "CALL db.idx.vector.queryNodes('DocChunk', 'embedding', $knn, vecf32($vector)) YIELD node, score\n"
        "WITH node AS c, 1.0 - score AS score\n"  # cosine distance -> similarity (higher = better)
        f"{_scope(by_doc)}"
        "WITH c, score ORDER BY score DESC LIMIT $k" + _HIT_TAIL
    )


class DocumentStore:
    """Document reads and writes on an existing GraphStore connection."""

    def __init__(self, graph: GraphStore) -> None:
        self.graph = graph
        self._dim: int | None = None

    def _query(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return self.graph._query(cypher, params)  # shares the store's connection and tracing

    def ensure_schema(self, embed_dim: int) -> None:
        if isinstance(embed_dim, bool) or not isinstance(embed_dim, int) or embed_dim <= 0:
            raise ValueError(f"embed_dim must be a positive int, got {embed_dim!r}")
        for statement in [*SCHEMA, _vector_index(embed_dim)]:
            try:
                self._query(statement)
            except GraphQueryError as exc:
                if "already indexed" not in str(exc).lower():
                    raise
        self._dim = embed_dim

    def write_document(
        self,
        doc_id: str,
        *,
        title: str,
        filename: str,
        language: str,
        pages: int,
        parts: int,
        size: int,
        chunks: list[Chunk],
        embeddings: list[list[float]] | None,
        embedder: str,
        digitised_by: str,
        status: str = "ready",
    ) -> dict[str, Any]:
        """Create or replace a document and all of its chunks."""
        if not doc_id or not isinstance(doc_id, str):
            raise ValueError("doc_id must be a non-empty string")
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError(f"got {len(embeddings)} embeddings for {len(chunks)} chunks")
        started = time.perf_counter()
        rows = [
            {
                "id": f"{doc_id}:c{chunk.seq:04d}",
                "doc_id": doc_id,
                "seq": chunk.seq,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "heading": chunk.heading,
                "text": chunk.text,
                "embedding": self._vector(embeddings[i]) if embeddings is not None else None,
            }
            for i, chunk in enumerate(chunks)
        ]
        with self.graph._write_lock:  # same writer lock as meeting writes
            self._query(UPSERT_DOCUMENT, {
                "id": doc_id, "title": (title or "").strip() or filename or "Untitled document",
                "filename": filename, "language": language, "pages": int(pages), "parts": int(parts),
                "bytes": int(size), "created_at": int(time.time() * 1000), "status": status,
                "embedder": embedder, "digitised_by": digitised_by,
            })
            self._query(DELETE_CHUNKS, {"id": doc_id})
            for start in range(0, len(rows), 200):
                self._query(WRITE_CHUNKS, {"rows": rows[start:start + 200]})
        return {"written": len(rows), "ms": round((time.perf_counter() - started) * 1000.0, 2)}

    def _vector(self, values: list[float]) -> list[float] | None:
        vector = [float(v) for v in values]
        if self._dim is not None and len(vector) != self._dim:
            raise ValueError(f"chunk embedding has {len(vector)} dims; the index expects {self._dim}")
        return vector if vector and all(math.isfinite(v) for v in vector) else None

    def set_summary(self, doc_id: str, summary: str, model: str) -> None:
        self._query(SET_DOCUMENT_SUMMARY, {"id": doc_id, "summary": summary, "model": model})

    def list_documents(self) -> list[dict[str, Any]]:
        return [_document(row) for row in self._query(LIST_DOCUMENTS)]

    def get_document(self, doc_id: str, with_chunks: bool = True) -> dict[str, Any] | None:
        rows = self._query(ONE_DOCUMENT, {"id": doc_id})
        if not rows:
            return None
        document = _document(rows[0])
        if with_chunks:
            document["chunks"] = [_chunk(row) for row in self._query(DOCUMENT_CHUNKS, {"id": doc_id})]
        return document

    def delete_document(self, doc_id: str) -> bool:
        with self.graph._write_lock:
            self._query(DELETE_CHUNKS, {"id": doc_id})
            rows = self._query(DELETE_DOCUMENT, {"id": doc_id})
        return bool(rows and rows[0].get("deleted"))

    def meeting_starts(self, meeting_ids: list[str]) -> list[dict[str, Any]]:
        """Start times of meetings, so answers can tell which source is newer."""
        return self._query(MEETING_STARTS, {"ids": list(meeting_ids)}) if meeting_ids else []

    def search_fulltext(self, query: str, k: int = 8, doc_id: str | None = None) -> list[dict[str, Any]]:
        """Text matches: the full-text index for Latin-script words, a substring scan for other scripts."""
        k = max(1, min(int(k), 200))
        scope: dict[str, Any] = {"doc_id": doc_id} if doc_id else {}
        rows: list[dict[str, Any]] = []
        terms = query_terms(query)
        if terms:
            try:
                rows += self._query(fulltext_chunks(bool(doc_id)), {"query": fulltext_query(terms), "k": k, **scope})
            except GraphQueryError as exc:
                log.warning("document full-text search for %r failed: %s", query, exc)
        native = native_terms(query)
        if native:
            rows += self._query(scan_chunks(bool(doc_id)),
                                {"terms": native, "k": k, "scan_limit": SCAN_LIMIT, **scope})
        hits: dict[str, dict[str, Any]] = {}
        for row in rows:
            hits.setdefault(row["id"], _hit(row, "fulltext"))
        return list(hits.values())[:k]

    def search_vector(self, vector: list[float], k: int = 8, doc_id: str | None = None) -> list[dict[str, Any]]:
        values = [float(v) for v in vector or []]
        if not values or not all(math.isfinite(v) for v in values):
            return []
        k = max(1, min(int(k), 200))
        params: dict[str, Any] = {"vector": values, "k": k, "knn": min(max(k * 10, 100), 1000) if doc_id else k}
        if doc_id:
            params["doc_id"] = doc_id
        try:
            rows = self._query(vector_chunks(bool(doc_id)), params)
        except GraphQueryError as exc:
            if "undefined attribute" in str(exc).lower() or "no such index" in str(exc).lower():
                return []
            raise
        return [_hit(row, "vector") for row in rows]


def _document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row.get("title") or row.get("filename") or "Untitled document",
        "filename": row.get("filename") or "",
        "language": row.get("language") or "",
        "pages": int(row.get("pages") or 0),
        "parts": int(row.get("parts") or 0),
        "bytes": int(row.get("bytes") or 0),
        "created_at": int(row.get("created_at") or 0),
        "status": row.get("status") or "ready",
        "summary": row.get("summary"),
        "summary_model": row.get("summary_model"),
        "embedder": row.get("embedder"),
        "digitised_by": row.get("digitised_by"),
        "chunk_count": int(row.get("chunk_count") or 0),
    }


def _chunk(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "seq": int(row.get("seq") or 0),
        "page_start": int(row.get("page_start") or 0),
        "page_end": int(row.get("page_end") or 0),
        "heading": row.get("heading") or "",
        "text": row.get("text") or "",
    }


def _hit(row: dict[str, Any], via: str) -> dict[str, Any]:
    hit = _chunk(row)
    hit.update(doc_id=row.get("doc_id"), doc_title=row.get("doc_title") or "", score=float(row.get("score") or 0.0),
               via=via)
    return hit
