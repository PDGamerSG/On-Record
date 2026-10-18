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

from ..brain.llm import UNTRUSTED_NOTE
from ..brain.retrieve import rrf_fuse
from ..contracts import LLM, Embedder
from .split import Chunk
from .store import DocumentStore

log = logging.getLogger(__name__)

_CITATION = re.compile(r"\[d:([^\]\s]+)\]")
_MEETING_CITATION = re.compile(r"\[u:([^\]\s]+)\]")
_GROUPED_CITATION = re.compile(r"\[\s*([du]:[^\]\s,;]+(?:\s*[,;]\s*[du]:[^\]\s,;]+)+)\s*\]")
SUMMARY_CHARS = 12000
ANCHOR_PASSAGES = 2  # top document passages also used as meeting queries
ANCHOR_CHARS = 300

ANSWER_SYSTEM = """You answer questions about the user's documents using only the numbered passages given.
Rules:
- Cite each statement with the id of the passage it came from, in square brackets, exactly as written,
  for example [d:doc-handbook-1a2b3c4d:c0003].
- If the passages do not answer the question, say that the documents do not cover it. Do not guess.
- Keep the answer short: two to five sentences or a short list.
- Reply in the language of the question.
"""
ANSWER_SYSTEM += UNTRUSTED_NOTE

ANSWER_WITH_MEETINGS_SYSTEM = """You answer questions using document passages ([d:...]) and meeting transcript lines ([u:...]).
Rules:
- Cite each statement with the id of the passage or line it came from, in square brackets, exactly as written.
- Meetings record what the team decided later than or apart from the documents. When a meeting line and a
  document disagree (an amount, date, owner or decision), say so plainly, cite both, and say which is newer
  if the dates show it.
- If neither source answers the question, say so. Do not guess.
- Keep the answer short: two to six sentences or a short list.
- Reply in the language of the question.
"""
ANSWER_WITH_MEETINGS_SYSTEM += UNTRUSTED_NOTE

SUMMARY_SYSTEM = """You summarise a document for a team that will discuss it in meetings.
Write a title-free summary in plain text: one sentence on what the document is, then up to five short
bullet points ("- ") covering decisions, deadlines, owners, amounts and obligations it states.
Only use facts that appear in the text.
"""
SUMMARY_SYSTEM += UNTRUSTED_NOTE


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


def meeting_lines(hits: list[dict[str, Any]]) -> str:
    lines = []
    for hit in hits:
        when = f", {hit['meeting_date']}" if hit.get("meeting_date") else ""
        minute, second = divmod(int(hit.get("t_start") or 0), 60)
        who = hit.get("speaker_name") or hit.get("speaker") or "Unknown speaker"
        lines.append(f"[u:{hit['utterance_id']}] Meeting \"{hit.get('meeting_title', '')}\"{when}, "
                     f"{who} at {minute:02d}:{second:02d}: {hit.get('text', '')}")
    return "\n".join(lines)


def split_grouped_citations(text: str) -> str:
    """Rewrite "[u:a, u:b]" as "[u:a] [u:b]" so every citation is checked and rendered on its own."""
    return _GROUPED_CITATION.sub(lambda m: " ".join(f"[{part.strip()}]" for part in re.split(r"[,;]", m.group(1))),
                                 text)


def _cited(pattern: re.Pattern[str], text: str, by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    cited: list[dict[str, Any]] = []
    for item_id in pattern.findall(text):
        if item_id in by_id and by_id[item_id] not in cited:
            cited.append(by_id[item_id])
    return cited


async def answer_question(
    llm: LLM,
    retriever: DocumentRetriever,
    question: str,
    *,
    doc_id: str | None = None,
    k: int = 6,
    meetings: Any | None = None,
    meeting_k: int = 6,
) -> dict[str, Any]:
    """Answer from document passages, and from meeting lines too when a meeting `Retriever` is given."""
    started = time.perf_counter()
    hits = retriever.retrieve(question, k, doc_id)
    meeting_hits: list[dict[str, Any]] = []
    if meetings is not None:
        try:
            meeting_hits = _meeting_hits(meetings, question, hits, meeting_k)
            _add_meeting_dates(retriever.docs, meeting_hits)
        except Exception as exc:  # noqa: BLE001 - document passages still answer the question
            log.warning("meeting retrieval for a document question failed: %r", exc)
    retrieval_ms = round((time.perf_counter() - started) * 1000, 1)
    if not hits and not meeting_hits:
        return {"answer": "The uploaded documents do not mention that.", "citations": [], "hits": [],
                "meeting_citations": [], "meeting_hits": [], "model": None, "provider": None,
                "timings": {"retrieval_ms": retrieval_ms}}
    context = f"Passages:\n\n{passages(hits)}" if hits else "Passages: none"
    if meetings is not None:
        context += f"\n\nMeeting lines:\n{meeting_lines(meeting_hits) if meeting_hits else 'none'}"
    result = await llm.chat(
        [
            {"role": "system", "content": ANSWER_WITH_MEETINGS_SYSTEM if meetings is not None else ANSWER_SYSTEM},
            {"role": "user", "content": f"{context}\n\nQuestion: {question.strip()}"},
        ],
        temperature=0.1,
        max_tokens=800,
    )
    by_id = {hit["id"]: hit for hit in hits}
    by_utterance = {hit["utterance_id"]: hit for hit in meeting_hits}
    answer = _CITATION.sub(lambda m: m.group(0) if m.group(1) in by_id else "", split_grouped_citations(result.text))
    answer = _MEETING_CITATION.sub(lambda m: m.group(0) if m.group(1) in by_utterance else "", answer).strip()
    return {
        "answer": answer,
        "citations": _cited(_CITATION, answer, by_id),
        "hits": hits,
        "meeting_citations": _cited(_MEETING_CITATION, answer, by_utterance),
        "meeting_hits": meeting_hits,
        "model": result.model,
        "provider": result.provider,
        "timings": {"retrieval_ms": retrieval_ms, "model_ms": result.latency_ms},
    }


def _meeting_hits(meetings: Any, question: str, doc_hits: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Meeting lines for the question, plus lines about the facts in the top passages.

    A long question can miss the meeting line that changed a number; searching with the passage text
    itself ("Starter costs Rs. 4,999 with 1,500 shipments") finds the lines that discuss the same facts.
    """
    queries = [question]
    for hit in doc_hits[:ANCHOR_PASSAGES]:
        heading = re.sub(r"^[\d.\s]+", "", hit.get("heading") or "").strip()  # "2. Starter plan" -> "Starter plan"
        if heading:
            queries.append(heading)
        queries.append(f"{heading} {hit.get('text', '')}"[:ANCHOR_CHARS])
    ranked = [meetings.retrieve(query, k=k)[0] for query in dict.fromkeys(queries)]
    return rrf_fuse(ranked, k + 3)


def _add_meeting_dates(docs: DocumentStore, hits: list[dict[str, Any]]) -> None:
    ids = sorted({hit["meeting_id"] for hit in hits if hit.get("meeting_id")})
    if not ids:
        return
    started = {row["id"]: row["started_at"] for row in docs.meeting_starts(ids)}
    for hit in hits:
        ms = started.get(hit.get("meeting_id"))
        if isinstance(ms, int | float) and ms > 0:
            hit["meeting_date"] = time.strftime("%d %b %Y", time.localtime(ms / 1000))


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
