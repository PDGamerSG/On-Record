"""Grounded meeting question orchestration.

The agent coordinates retrieval, a language-model response, citation filtering and short-lived
conversation history. It deliberately keeps model and graph concerns behind the existing protocols so
the orchestration path can be exercised without external services.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..contracts import LLM, AskResult
from .llm import UNTRUSTED_NOTE
from .retrieve import Retriever

_CITATION = re.compile(r"\[u:([^\]\s]+)\]")
_FALLBACK = "I couldn't find supporting evidence in the meeting record."
_SYSTEM_PROMPT = """You answer questions about meeting transcripts using only the evidence provided.
Keep answers concise and cite each factual statement with the exact [u:<utterance_id>] marker.
If the evidence does not answer the question, say so plainly and do not guess.
"""
_SYSTEM_PROMPT += UNTRUSTED_NOTE


class MeetingAgent:
    """Coordinate retrieval and grounded language-model answers for meeting questions."""

    def __init__(self, llm: LLM, retriever: Retriever, *, history_turns: int = 6) -> None:
        if history_turns <= 0:
            raise ValueError("history_turns must be positive")
        self.llm = llm
        self.retriever = retriever
        self.history_turns = history_turns
        self._history: dict[str, list[dict[str, str]]] = {}

    async def ask(
        self,
        question: str,
        *,
        session_id: str = "default",
        meeting_id: str | None = None,
        k: int = 8,
    ) -> AskResult:
        """Retrieve evidence and answer a question while preserving citation integrity."""
        question = question.strip()
        if not question:
            raise ValueError("question must not be blank")
        session_id = session_id.strip() or "default"

        started = time.perf_counter()
        hits, cypher = self.retriever.retrieve(question, meeting_id=meeting_id, k=k)
        retrieval_ms = round((time.perf_counter() - started) * 1000, 1)
        tool_trace = [{
            "tool": "search_meetings",
            "args": {"meeting_id": meeting_id, "query": question, "k": k},
            "result_count": len(hits),
            "ms": retrieval_ms,
        }]
        if not hits:
            return self._result(
                _FALLBACK,
                [],
                cypher,
                session_id,
                tool_trace=tool_trace,
                retrieval_ms=retrieval_ms,
                total_ms=round((time.perf_counter() - started) * 1000, 1),
            )

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            *self._history.get(session_id, []),
            {"role": "user", "content": f"Evidence:\n{_evidence(hits)}\n\nQuestion: {question}"},
        ]
        model_started = time.perf_counter()
        response = await self.llm.chat(messages, temperature=0.1, max_tokens=500)
        model_ms = round((time.perf_counter() - model_started) * 1000, 1)
        answer, citations = _ground(response.text, hits)
        answer = answer or _FALLBACK
        self._remember(session_id, question, answer)
        return self._result(
            answer,
            citations,
            cypher,
            session_id,
            tool_trace=tool_trace,
            retrieval_ms=retrieval_ms,
            model_ms=model_ms,
            total_ms=round((time.perf_counter() - started) * 1000, 1),
            model=response.model,
            provider=response.provider,
        )

    def clear_session(self, session_id: str) -> None:
        """Forget conversation context for a session."""
        self._history.pop(session_id.strip() or "default", None)

    def _remember(self, session_id: str, question: str, answer: str) -> None:
        history = self._history.setdefault(session_id, [])
        history.extend(({"role": "user", "content": question}, {"role": "assistant", "content": answer}))
        del history[: -self.history_turns * 2]

    def _result(
        self,
        answer: str,
        citations: list[dict[str, Any]],
        cypher: list[str],
        session_id: str,
        *,
        tool_trace: list[dict[str, Any]],
        retrieval_ms: float,
        total_ms: float,
        model_ms: float | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> AskResult:
        timings = {"retrieval_ms": retrieval_ms, "total_ms": total_ms}
        if model_ms is not None:
            timings["model_ms"] = model_ms
        return AskResult(
            answer=answer,
            citations=citations,
            actions=[],
            tool_trace=tool_trace,
            cypher=cypher,
            model=model or self.llm.model,
            provider=provider or self.llm.provider,
            session_id=session_id,
            timings=timings,
        )


def _evidence(hits: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for hit in hits:
        utterance_id = hit.get("utterance_id") or hit.get("id")
        if not utterance_id:
            continue
        speaker = hit.get("speaker_name") or hit.get("speaker") or "Unknown speaker"
        timestamp = _mmss(float(hit.get("t_start") or 0.0))
        text = " ".join(str(hit.get("text") or "").split())
        lines.append(f"[u:{utterance_id}] {speaker} at {timestamp}: {text}")
    return "\n".join(lines)


def _ground(text: str, hits: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    by_id = {str(hit.get("utterance_id") or hit.get("id")): hit for hit in hits}
    citations: list[dict[str, Any]] = []

    def replace(match: re.Match[str]) -> str:
        utterance_id = match.group(1)
        hit = by_id.get(utterance_id)
        if hit is None:
            return ""
        if hit not in citations:
            citations.append(hit)
        return match.group(0)

    clean = _CITATION.sub(replace, text)
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
    return " ".join(clean.split()).strip(), citations


def _mmss(seconds: float) -> str:
    minutes, remainder = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d}:{remainder:02d}"
