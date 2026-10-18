"""Document search and Gemma 4 answers with page citations.

DocumentRetriever fuses full-text and vector matches over DocChunk nodes with the same reciprocal-rank
fusion used for meetings. Answers may only cite passages that were retrieved; any other citation the
model invents is dropped before the answer is returned.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..brain.retrieve import rrf_fuse
from ..contracts import LLM, Embedder
from .split import Chunk
from .store import DocumentStore

log = logging.getLogger(__name__)

_CITATION = re.compile(r"\[d:([^\]\s]+)\]")
SUMMARY_CHARS = 12000

ANSWER_SYSTEM = """You answer questions about the user's documents using only the numbered passages given.
Rules:
- Cite each statement with the id of the passage it came from, in square brackets, exactly as written,
  for example [d:doc-handbook-1a2b3c4d:c0003].
- If the passages do not answer the question, say that the documents do not cover it. Do not guess.
- Keep the answer short: two to five sentences or a short list.
- Reply in the language of the question."""

SUMMARY_SYSTEM = """You summarise a document for a team that will discuss it in meetings.
Write a title-free summary in plain text: one sentence on what the document is, then up to five short
bullet points ("- ") covering decisions, deadlines, owners, amounts and obligations it states.
Only use facts that appear in the text."""


class DocumentRetriever:
    def __init__(self, docs: DocumentStore, embedder: Embedder) -> None:
        self.docs = docs
        self.embedder = embedder

    def retrieve(self, question: str, k: int = 6, doc_id: str | None = None) -> list[dict[str, Any]]:
        if not question or not question.strip():
            return []
        lists = [self.docs.search_fulltext(question, k * 2, doc_id)]
        try:
            vector = self.embedder.embed_query(question)
            lists.append(self.docs.search_vector(vector, k * 2, doc_id))
        except Exception as exc:  # noqa: BLE001 - full-text results still answer the question
            log.warning("document vector search failed: %r", exc)
        hits = rrf_fuse(lists, k)
        for hit in hits:
            hit.pop("utterance_id", None)
        return hits


def pages_label(hit: dict[str, Any]) -> str:
    start, end = hit.get("page_start") or 0, hit.get("page_end") or 0
    return f"p. {start}" if start == end else f"pp. {start}-{end}"


def passages(hits: list[dict[str, Any]]) -> str:
    blocks = []
    for hit in hits:
        heading = f" — {hit['heading']}" if hit.get("heading") else ""
        blocks.append(f"[d:{hit['id']}] {hit.get('doc_title', '')}, {pages_label(hit)}{heading}\n{hit['text']}")
    return "\n\n".join(blocks)


async def answer_question(
    llm: LLM, retriever: DocumentRetriever, question: str, *, doc_id: str | None = None, k: int = 6
) -> dict[str, Any]:
    started = time.perf_counter()
    hits = retriever.retrieve(question, k, doc_id)
    retrieval_ms = round((time.perf_counter() - started) * 1000, 1)
    if not hits:
        return {"answer": "The uploaded documents do not mention that.", "citations": [], "hits": [],
                "model": None, "provider": None, "timings": {"retrieval_ms": retrieval_ms}}
    result = await llm.chat(
        [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"Passages:\n\n{passages(hits)}\n\nQuestion: {question.strip()}"},
        ],
        temperature=0.1,
        max_tokens=700,
    )
    by_id = {hit["id"]: hit for hit in hits}
    cited: list[dict[str, Any]] = []
    for chunk_id in _CITATION.findall(result.text):
        if chunk_id in by_id and by_id[chunk_id] not in cited:
            cited.append(by_id[chunk_id])
    answer = _CITATION.sub(lambda m: m.group(0) if m.group(1) in by_id else "", result.text).strip()
    return {
        "answer": answer,
        "citations": cited,
        "hits": hits,
        "model": result.model,
        "provider": result.provider,
        "timings": {"retrieval_ms": retrieval_ms, "model_ms": result.latency_ms},
    }


async def summarise_document(llm: LLM, title: str, chunks: list[Chunk]) -> dict[str, Any]:
    text, used = [], 0
    for chunk in chunks:
        piece = f"(p. {chunk.page_start}) {chunk.heading + ': ' if chunk.heading else ''}{chunk.text}"
        if used + len(piece) > SUMMARY_CHARS:
            break
        text.append(piece)
        used += len(piece)
    result = await llm.chat(
        [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": f"Document: {title}\n\n" + "\n\n".join(text)},
        ],
        temperature=0.2,
        max_tokens=500,
    )
    return {"text": result.text.strip(), "model": result.model, "provider": result.provider}
