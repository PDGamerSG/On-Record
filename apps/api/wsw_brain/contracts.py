"""Shared types and interfaces. Every module codes against these; keep them stable.

Layers:
  listen/  audio -> Utterance (speaker-attributed, timestamped)      [ListenerCallbacks]
  graph/   GraphStore: FalkorDB writes + reads                        [GraphStore]
  brain/   LLM (Gemma 4 adapter), Embedder, Extractor, Agent          [LLM, Embedder, Extractor]
  api/     FastAPI wiring (REST, SSE, WebSocket)

All times on utterances are SECONDS from meeting start. Wall-clock times are epoch milliseconds.
Graph dicts returned to the API are plain JSON-serialisable dicts with the keys documented here.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import numpy as np

SAMPLE_RATE = 16_000


# ---------------------------------------------------------------------------
# Listener output
# ---------------------------------------------------------------------------


@dataclass
class Utterance:
    """One speaker turn produced by the listener (before it is written to the graph).

    Invalid identifiers, sequence numbers, timestamps, or confidence raise ValueError at construction.
    """

    meeting_id: str
    seq: int  # 0-based order within the meeting
    speaker: str  # meeting-scoped speaker track, "S1", "S2", ...
    t_start: float
    t_end: float
    text: str
    confidence: float = 1.0  # speaker-assignment confidence in [0, 1]

    def __post_init__(self) -> None:
        for name in ("meeting_id", "speaker"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Utterance.{name} must be a non-empty string")
        if isinstance(self.seq, bool) or not isinstance(self.seq, int) or self.seq < 0:
            raise ValueError("Utterance.seq must be a non-negative int")
        for name in ("t_start", "t_end", "confidence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Utterance.{name} must be a finite number")
        if self.t_start < 0:
            raise ValueError("Utterance.t_start must be non-negative")
        if self.t_end < self.t_start:
            raise ValueError("Utterance.t_end must be greater than or equal to t_start")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Utterance.confidence must be between 0 and 1")

    @property
    def id(self) -> str:
        return f"{self.meeting_id}:u{self.seq:05d}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        return d


@dataclass
class ListenerCallbacks:
    """Called from the listener's worker thread."""

    on_utterance: Callable[[Utterance], None]
    on_speaker_merged: Callable[[str, str, str], None] = lambda meeting_id, src, dst: None  # (meeting_id, from, to)
    on_status: Callable[[str, dict[str, Any]], None] = lambda state, detail: None


class ASR(Protocol):
    name: str

    def transcribe(self, samples: np.ndarray) -> tuple[str, float]:
        """16 kHz mono float32 in [-1, 1] -> (text, confidence in [0, 1])."""
        ...


@runtime_checkable
class FileASR(ASR, Protocol):
    """ASR adapter that can decode and transcribe an audio file in one call."""

    def transcribe_file(
        self, path: str | Path, *, max_duration_s: float | None = None
    ) -> tuple[str, float]:
        """Decode an audio path and return (text, confidence in [0, 1])."""
        ...


class SpeakerEmbedder(Protocol):
    name: str
    dim: int

    def embed(self, samples: np.ndarray) -> np.ndarray:
        """16 kHz mono float32 -> L2-normalised voice embedding (float32, shape [dim])."""
        ...


# ---------------------------------------------------------------------------
# Graph dict shapes (what GraphStore returns and the API serves)
# ---------------------------------------------------------------------------
#
# MeetingSummary: {id, title, status: "live"|"ended", source: "mic"|"upload"|"demo", started_at (ms),
#                  ended_at (ms|None), duration_s, utterance_count, speaker_count, has_audio: bool, summary}
# Speaker:        {track, label, name|None, person_id|None, color_idx, utterance_count, talk_time_s}
# UtteranceOut:   {id, meeting_id, seq, speaker, speaker_name|None, t_start, t_end, text, confidence}
# Decision:       {id, meeting_id, text, status: "active"|"superseded", made_at, proposed_by|None,
#                  evidence: [utterance_id], superseded_by: id|None, supersedes: id|None}
# ActionItem:     {id, meeting_id, meeting_title, text, owner (name or speaker label)|None, owner_track|None,
#                  due|None, status: "open"|"done", created_at (ms), done_at (ms|None), evidence: [utterance_id]}
# Topic:          {id, name, mentions: int}
# Hit/Citation:   {utterance_id, meeting_id, meeting_title, speaker, speaker_name|None, t_start, t_end,
#                  text, score: float (higher = better), via: "fulltext"|"vector"|"graph"|"recent"}
# Subgraph:       {nodes: [{id, label, kind, ...}], links: [{source, target, type}]}


@dataclass
class DecisionDraft:
    text: str
    evidence: list[str]  # utterance ids
    proposed_by: str | None = None  # speaker track
    supersedes_text: str | None = None  # text of an earlier decision this one replaces, if any

    def __post_init__(self) -> None:
        _require_text(self.text, "DecisionDraft.text")
        _require_evidence(self.evidence, "DecisionDraft.evidence")
        _require_optional_text(self.proposed_by, "DecisionDraft.proposed_by")
        _require_optional_text(self.supersedes_text, "DecisionDraft.supersedes_text")


@dataclass
class ActionItemDraft:
    text: str
    evidence: list[str]
    owner: str | None = None  # speaker track ("S2") or a person name
    due: str | None = None  # free text as spoken ("Friday", "next sprint")

    def __post_init__(self) -> None:
        _require_text(self.text, "ActionItemDraft.text")
        _require_evidence(self.evidence, "ActionItemDraft.evidence")
        _require_optional_text(self.owner, "ActionItemDraft.owner")
        _require_optional_text(self.due, "ActionItemDraft.due")


def _require_text(value: object, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")


def _require_optional_text(value: object, field: str) -> None:
    if value is not None:
        _require_text(value, field)


def _require_evidence(value: object, field: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")


def _require_entities(value: object) -> None:
    if not isinstance(value, list) or any(not isinstance(entity, dict) for entity in value):
        raise ValueError("Insights.entities must be a list of dictionaries")
    for entity in value:
        _require_text(entity.get("name"), "Insights.entities.name")
        if "kind" in entity:
            _require_text(entity["kind"], "Insights.entities.kind")


def _require_mentions(value: object) -> None:
    if not isinstance(value, dict):
        raise TypeError("Insights.mentions must be a dictionary")
    for utterance_id, names in value.items():
        _require_text(utterance_id, "Insights.mentions.utterance_id")
        if not isinstance(names, list) or any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("Insights.mentions values must be lists of non-empty strings")


@dataclass
class Insights:
    decisions: list[DecisionDraft] = field(default_factory=list)
    action_items: list[ActionItemDraft] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)  # {name, kind}
    mentions: dict[str, list[str]] = field(default_factory=dict)  # utterance_id -> topic/entity names

    def __post_init__(self) -> None:
        if not isinstance(self.decisions, list) or any(not isinstance(item, DecisionDraft) for item in self.decisions):
            raise ValueError("Insights.decisions must be a list of DecisionDraft values")
        if not isinstance(self.action_items, list) or any(
            not isinstance(item, ActionItemDraft) for item in self.action_items
        ):
            raise ValueError("Insights.action_items must be a list of ActionItemDraft values")
        if not isinstance(self.topics, list) or any(not isinstance(topic, str) or not topic.strip() for topic in self.topics):
            raise ValueError("Insights.topics must be a list of non-empty strings")
        _require_entities(self.entities)
        _require_mentions(self.mentions)

    def is_empty(self) -> bool:
        return not (self.decisions or self.action_items or self.topics or self.entities)


# ---------------------------------------------------------------------------
# Gemma 4 adapter
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResult:
    text: str
    tool_calls: list[ToolCall]
    model: str
    provider: str  # "ollama" | "gemini" | "openai" | "fake"
    latency_ms: float


@dataclass
class Transcript:
    text: str
    model: str
    provider: str  # "gemma4-audio:ollama" | "whisper"
    latency_ms: float


class LLM(Protocol):
    provider: str
    model: str
    supports_audio: bool

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResult:
        """messages: [{"role": "system"|"user"|"assistant"|"tool", "content": str, ("name": tool name)}].
        tools: JSON-schema function declarations [{"name", "description", "parameters"}]."""
        ...

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        """Native audio understanding (Gemma 4 E2B/E4B/12B). Raise NotImplementedError if unsupported."""
        ...


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# Agent output
# ---------------------------------------------------------------------------


@dataclass
class AskResult:
    answer: str
    citations: list[dict[str, Any]]  # Hit/Citation dicts actually cited in the answer
    actions: list[dict[str, Any]]  # client actions: {"type": "seek"|"open_meeting"|"refresh", ...}
    tool_trace: list[dict[str, Any]]  # [{"tool", "args", "result_count", "ms"}]
    cypher: list[str]  # Cypher statements that produced the evidence
    model: str
    provider: str
    session_id: str
    timings: dict[str, float] = field(default_factory=dict)  # ms: retrieve, llm, total
    transcript: str | None = None  # for voice questions: what was heard
    transcript_provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Status = Literal["open", "done"]
