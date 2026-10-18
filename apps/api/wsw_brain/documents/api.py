"""HTTP routes for documents: upload (split + digitise in the background), list, read, search and ask.

`router` is meant to be mounted on the main application. Until that application lands, `app.py` serves
it on its own so the web Documents page can run against a real backend.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from ..brain import Retriever, get_embedder, get_llm
from ..config import settings
from ..graph import GraphError, GraphStore
from ..sarvam import SarvamSpeech, SarvamSpeechError, translator_name
from .answer import DocumentRetriever, answer_question
from .ingest import DocumentIngestor, new_document_id
from .sarvam import SarvamDocAI, SarvamError
from .split import DocumentError, detect_kind, split_document
from .store import DocumentStore

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])
JOB_TTL_S = 3600


@dataclass
class IngestJob:
    id: str
    doc_id: str
    filename: str
    status: str = "running"  # running | done | failed
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)

    def view(self) -> dict[str, Any]:
        return {"id": self.id, "doc_id": self.doc_id, "filename": self.filename, "status": self.status,
                "events": self.events[-50:], "result": self.result, "error": self.error}


_jobs: dict[str, IngestJob] = {}
_tasks: set[asyncio.Task[None]] = set()


LANGUAGE_PATTERN = r"^[a-z]{2,3}-IN$"
TRANSLATE_TIMEOUT_S = 20.0  # a slow translation must not hold back the English answer


class AskBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    doc_id: str | None = None
    k: int = Field(6, ge=1, le=20)
    # Optional reply language (e.g. "kn-IN"); the answer is also returned translated by Sarvam.
    language: str | None = Field(None, pattern=LANGUAGE_PATTERN)
    # Also search meeting transcripts, so Gemma 4 can point out where meetings changed what a document says.
    include_meetings: bool = False


class SpeakBody(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str = Field("en-IN", pattern=LANGUAGE_PATTERN)
    speaker: str = Field("priya", pattern=r"^[a-z_]{2,40}$")
    pace: float = Field(1.0, ge=0.5, le=2.0)


@lru_cache(maxsize=1)
def _docs() -> DocumentStore:
    s = settings()
    return DocumentStore(GraphStore(s.falkordb_url, s.graph))


@lru_cache(maxsize=1)
def _digitiser() -> SarvamDocAI:
    s = settings()
    if not s.sarvam_api_key:
        raise HTTPException(503, "Document AI needs SARVAM_API_KEY in .env")
    return SarvamDocAI(s.sarvam_api_key, s.sarvam_base_url)


@lru_cache(maxsize=1)
def _speech() -> SarvamSpeech:
    s = settings()
    if not s.sarvam_api_key:
        raise HTTPException(503, "translation and speech need SARVAM_API_KEY in .env")
    return SarvamSpeech(s.sarvam_api_key, s.sarvam_base_url)


@lru_cache(maxsize=1)
def _ingestor() -> DocumentIngestor:
    s = settings()
    return DocumentIngestor(
        _docs(), get_embedder(), _digitiser(), llm=get_llm(), language=s.doc_language,
        max_pages=s.doc_part_pages, max_total_pages=s.doc_max_pages, concurrency=s.doc_concurrency,
    )


def _graph_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except GraphError as exc:
        raise HTTPException(503, f"graph database unavailable: {exc}") from exc


async def _read_upload(file: UploadFile) -> bytes:
    limit = int(settings().doc_max_mb * 1024 * 1024)
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"the file is larger than {settings().doc_max_mb:g} MB")
    if not data:
        raise HTTPException(400, "the file is empty")
    return data


@router.get("/status")
def status() -> dict[str, Any]:
    s = settings()
    llm = get_llm()
    embedder = get_embedder()
    return {
        "sarvam_configured": bool(s.sarvam_api_key),
        "digitiser": "Sarvam Vision (Document AI)",
        "llm": {"provider": llm.provider, "model": llm.model},
        "embedder": embedder.name,
        "part_pages": s.doc_part_pages,
        "max_pages": s.doc_max_pages,
        "max_mb": s.doc_max_mb,
        "language": s.doc_language,
    }


@router.post("/split")
async def preview_split(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """Show how an upload would be split for Document AI, without sending it to Sarvam."""
    data = await _read_upload(file)
    try:
        parts = split_document(file.filename or "document", data, settings().doc_part_pages)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "filename": file.filename,
        "kind": detect_kind(data),
        "pages": parts[-1].last_page,
        "part_pages": settings().doc_part_pages,
        "parts": [{"index": p.index, "filename": p.filename, "first_page": p.first_page,
                   "last_page": p.last_page, "pages": p.page_count, "bytes": len(p.data)} for p in parts],
    }


@router.post("")
async def upload(
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form()] = "",
    language: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """Start ingesting a document. Poll GET /api/documents/jobs/{id} for progress."""
    data = await _read_upload(file)
    filename = file.filename or "document"
    ingestor = _ingestor()
    try:
        parts = ingestor.plan(filename, data)
    except DocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    _prune_jobs()
    job = IngestJob(id=uuid.uuid4().hex[:12], doc_id=new_document_id(filename), filename=filename)
    _jobs[job.id] = job

    async def run() -> None:
        try:
            job.result = await ingestor.ingest(
                filename, data, title=title or None, doc_id=job.doc_id, language=language or None,
                on_progress=lambda event: job.events.append({**event, "at": time.time()}),
            )
            job.status = "done"
        except (DocumentError, SarvamError, GraphError, ValueError) as exc:
            job.status, job.error = "failed", str(exc)
            log.warning("document job %s failed: %s", job.id, exc)
        except Exception as exc:  # report every failure to the polling client
            job.status, job.error = "failed", f"unexpected error: {exc!r}"
            log.exception("document job %s failed", job.id)

    task = asyncio.create_task(run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"job": job.view(), "pages": parts[-1].last_page, "parts": len(parts)}


@router.get("/jobs")
def list_jobs(
    status: Literal["running", "done", "failed"] | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[dict[str, Any]]:
    """List recent document ingestion jobs for clients that need a job overview."""
    _prune_jobs()
    jobs = sorted(_jobs.values(), key=lambda item: item.started_at, reverse=True)
    if status is not None:
        jobs = [job for job in jobs if job.status == status]
    return [job.view() for job in jobs[:limit]]


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "no such document job")
    return job.view()


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, bool]:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "no such document job")
    if job.status == "running":
        raise HTTPException(409, "document job is still running")
    _jobs.pop(job_id)
    return {"deleted": True}


@router.get("")
def list_documents() -> list[dict[str, Any]]:
    return _graph_call(_docs().list_documents)


@router.get("/search")
def search(q: str, doc_id: str | None = None, k: int = 8) -> list[dict[str, Any]]:
    retriever = DocumentRetriever(_docs(), get_embedder())
    return _graph_call(retriever.retrieve, q, max(1, min(k, 20)), doc_id)


@router.post("/ask")
async def ask(body: AskBody) -> dict[str, Any]:
    retriever = DocumentRetriever(_docs(), get_embedder())
    try:
        meetings = Retriever(_docs().graph, get_embedder()) if body.include_meetings else None
        result = await answer_question(get_llm(), retriever, body.question, doc_id=body.doc_id, k=body.k,
                                       meetings=meetings)
    except GraphError as exc:
        raise HTTPException(503, f"graph database unavailable: {exc}") from exc
    if body.language and body.language != "en-IN":
        started = time.perf_counter()
        try:
            result["translated_answer"] = await asyncio.wait_for(
                _speech().translate(result["answer"], body.language), TRANSLATE_TIMEOUT_S
            )
            result["answer_language"] = body.language
            result["translated_by"] = translator_name(body.language)
        except (SarvamSpeechError, TimeoutError) as exc:
            detail = str(exc) or f"translation took longer than {TRANSLATE_TIMEOUT_S:g} s"
            log.warning("translating the answer to %s failed: %s", body.language, detail)
            result["translation_error"] = detail
        result["timings"]["translate_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


@router.post("/speak")
async def speak(body: SpeakBody) -> Response:
    """Read text aloud with Sarvam Bulbul v3; returns audio/wav."""
    try:
        audio = await _speech().speak(body.text, body.language, body.speaker, body.pace)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except SarvamSpeechError as exc:
        raise HTTPException(502, str(exc)) from exc
    return Response(audio, media_type="audio/wav", headers={"x-spoken-by": "Sarvam Bulbul v3"})


@router.get("/{doc_id}")
def get_document(doc_id: str) -> dict[str, Any]:
    document = _graph_call(_docs().get_document, doc_id)
    if document is None:
        raise HTTPException(404, "no such document")
    return document


@router.delete("/{doc_id}")
def delete_document(doc_id: str) -> dict[str, bool]:
    return {"deleted": _graph_call(_docs().delete_document, doc_id)}


def _prune_jobs() -> None:
    cutoff = time.time() - JOB_TTL_S
    for job_id in [j.id for j in _jobs.values() if j.status != "running" and j.started_at < cutoff]:
        _jobs.pop(job_id, None)

