"""HTTP and WebSocket integration for live meetings.

The graph, listener and agent modules are deliberately usable without FastAPI.  This module is the
thin adapter that turns those contracts into the routes consumed by the web application.  Dependencies
are kept on ``app.state`` so tests can inject fakes and importing the package never connects to FalkorDB
or downloads a model.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketState

from .brain.agent import MeetingAgent
from .config import Settings, settings
from .contracts import Transcript
from .graph import GraphError, GraphStore, GraphUnavailable
from .listen.asr import FasterWhisperASR
from .listen.audio import AudioTooLong, decode_file
from .listen.factory import get_speaker_embedder
from .listen.pipeline import process_file
from .listen.session import ListenerOverloaded, LiveSession
from .pipeline import IngestPipeline

log = logging.getLogger(__name__)


class CreateMeetingRequest(BaseModel):
    title: str = Field("Untitled meeting", min_length=1, max_length=120)


class SpeakerNameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ActionStatusRequest(BaseModel):
    status: Literal["open", "done"]


def create_router() -> APIRouter:
    """Build the routes consumed by ``apps/web/src/api/client.ts``."""

    router = APIRouter(tags=["meetings"])

    def runtime(request: Request) -> Any:
        ensure = getattr(request.app.state, "ensure_runtime", None)
        if ensure is not None:
            try:
                ensure()
            except (GraphUnavailable, GraphError, FileNotFoundError, RuntimeError) as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
        return request.app.state

    def store(request: Request) -> GraphStore:
        state = runtime(request)
        value = getattr(state, "graph_store", None)
        if value is None:
            raise HTTPException(status_code=503, detail="graph storage is not configured")
        return value

    def pipeline(request: Request) -> IngestPipeline | None:
        return getattr(runtime(request), "ingest_pipeline", None)

    def agent(request: Request) -> MeetingAgent:
        value = getattr(runtime(request), "meeting_agent", None)
        if value is None:
            raise HTTPException(status_code=503, detail="meeting assistant is not configured")
        return value

    def bus(request: Request) -> Any:
        return request.app.state.event_bus

    def error(exc: Exception) -> HTTPException:
        if isinstance(exc, LookupError):
            return HTTPException(status_code=404, detail=str(exc))
        if isinstance(exc, (ValueError, TypeError)):
            return HTTPException(status_code=422, detail=str(exc))
        if isinstance(exc, GraphUnavailable):
            return HTTPException(status_code=503, detail=str(exc))
        return HTTPException(status_code=500, detail="graph operation failed")

    @router.get("/api/meetings")
    def list_meetings(request: Request) -> list[dict[str, Any]]:
        try:
            return store(request).list_meetings()
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - adapter boundary
            raise error(exc) from exc

    @router.post("/api/meetings", status_code=201)
    def create_meeting(body: CreateMeetingRequest, request: Request) -> dict[str, Any]:
        graph = store(request)
        meeting_id = f"m-{uuid.uuid4().hex[:12]}"
        try:
            meeting = graph.create_meeting(meeting_id, body.title, "mic", int(time.time() * 1000))
            ingest = pipeline(request)
            if ingest is not None:
                ingest.begin_meeting(meeting_id)
            bus(request).publish("meeting.started", meeting, meeting_id)
            return meeting
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/meetings/{meeting_id}")
    def get_meeting(meeting_id: str, request: Request) -> dict[str, Any]:
        try:
            detail = store(request).get_meeting(meeting_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc
        if detail is None:
            raise HTTPException(status_code=404, detail=f"meeting {meeting_id} not found")
        return detail

    @router.get("/api/meetings/{meeting_id}/utterances")
    def utterances_after(
        meeting_id: str, request: Request, after_seq: int = Query(default=-1, ge=-1)
    ) -> list[dict[str, Any]]:
        try:
            return store(request).utterances_since(meeting_id, after_seq)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.post("/api/meetings/{meeting_id}/end")
    async def end_meeting(meeting_id: str, request: Request) -> dict[str, Any]:
        ingest = pipeline(request)
        try:
            if ingest is not None:
                meeting = await ingest.end_meeting(meeting_id, wait_final=False, publish_event=False)
                if meeting is not None:
                    bus(request).publish("meeting.ended", meeting, meeting_id)
            else:
                existing = store(request).get_meeting(meeting_id)
                if existing is None:
                    meeting = None
                else:
                    summary = existing["meeting"]
                    duration = float(summary.get("duration_s") or 0.0)
                    meeting = store(request).end_meeting(meeting_id, int(time.time() * 1000), duration)
                    if meeting is not None:
                        bus(request).publish("meeting.ended", meeting, meeting_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc
        if meeting is None:
            raise HTTPException(status_code=404, detail=f"meeting {meeting_id} not found")
        return meeting

    @router.delete("/api/meetings/{meeting_id}")
    def delete_meeting(meeting_id: str, request: Request) -> dict[str, bool]:
        try:
            graph = store(request)
            ingest = pipeline(request)
            deleted = graph.delete_meeting(meeting_id)
            if deleted and ingest is not None:
                ingest.forget(meeting_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail=f"meeting {meeting_id} not found")
        recording = settings().audio_dir / f"{meeting_id}.wav"
        with contextlib.suppress(OSError):
            recording.unlink()
        return {"deleted": True}

    @router.patch("/api/meetings/{meeting_id}/speakers/{track}")
    def name_speaker(meeting_id: str, track: str, body: SpeakerNameRequest, request: Request) -> dict[str, Any]:
        try:
            named = store(request).name_speaker(meeting_id, track, body.name)
            ingest = pipeline(request)
            if ingest is not None:
                ingest.speaker_named(meeting_id, track, body.name)
            bus(request).publish(
                "speaker.named",
                {"track": named["track"], "name": named["name"], "person_id": named.get("person_id")},
                meeting_id,
            )
            return named
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/meetings/{meeting_id}/audio")
    def meeting_audio(meeting_id: str, request: Request) -> FileResponse:
        detail = get_meeting(meeting_id, request)
        if not detail["meeting"].get("has_audio"):
            raise HTTPException(status_code=404, detail="meeting has no recording")
        path = settings().audio_dir / f"{meeting_id}.wav"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="meeting recording is not available")
        return FileResponse(path, media_type="audio/wav", filename=f"{meeting_id}.wav")

    @router.post("/api/meetings/upload", status_code=201)
    async def upload_meeting(
        request: Request,
        background: BackgroundTasks,
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
        title: str = Form("Uploaded recording"),
        pace: Literal["fast", "realtime"] = Form("fast"),
    ) -> dict[str, Any]:
        ingest = pipeline(request)
        if ingest is None:
            raise HTTPException(status_code=503, detail="live ingestion is not configured")
        _start_ingest(request.app.state)
        suffix = Path(file.filename or "recording").suffix.lower() or ".audio"
        incoming_dir = settings().audio_dir / ".incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)
        source = incoming_dir / f"{uuid.uuid4().hex}{suffix}"
        scheduled = False
        try:
            source.write_bytes(await file.read())
            graph = store(request)
            meeting_id = f"m-{uuid.uuid4().hex[:12]}"
            meeting = graph.create_meeting(meeting_id, title, "upload", int(time.time() * 1000))
            ingest.begin_meeting(meeting_id)
            audio_path = settings().audio_dir / f"{meeting_id}.wav"
            background.add_task(_process_upload, request, source, meeting_id, pace, audio_path)
            scheduled = True
            return meeting
        except HTTPException:
            if not scheduled:
                with contextlib.suppress(OSError):
                    source.unlink()
            raise
        except (AudioTooLong, ValueError) as exc:
            if not scheduled:
                with contextlib.suppress(OSError):
                    source.unlink()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            if not scheduled:
                with contextlib.suppress(OSError):
                    source.unlink()
            raise error(exc) from exc

    @router.get("/api/stats")
    def stats(request: Request) -> dict[str, int]:
        try:
            return store(request).stats()
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/action-items")
    def action_items(
        request: Request,
        status: Literal["open", "done"] | None = Query(default=None),
        owner: str | None = Query(default=None),
        meeting_id: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        try:
            return store(request).list_action_items(status=status, owner=owner, meeting_id=meeting_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.patch("/api/action-items/{item_id}")
    def set_action_item(item_id: str, body: ActionStatusRequest, request: Request) -> dict[str, Any]:
        try:
            item = store(request).set_action_item_status(item_id, body.status)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc
        if item is None:
            raise HTTPException(status_code=404, detail=f"action item {item_id} not found")
        bus(request).publish("action.updated", item, item.get("meeting_id"))
        return item

    @router.get("/api/decisions")
    def decisions(request: Request, meeting_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
        try:
            return store(request).list_decisions(meeting_id=meeting_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/people")
    def people(request: Request) -> list[dict[str, Any]]:
        try:
            return store(request).list_people()
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/who-knows")
    def who_knows(request: Request, topic: str = Query(min_length=1, max_length=200)) -> list[dict[str, Any]]:
        try:
            return store(request).who_knows(topic)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/graph")
    def graph(
        request: Request,
        meeting_id: str | None = Query(default=None),
        utterance_ids: str | None = Query(default=None),
    ) -> dict[str, Any]:
        ids = [value.strip() for value in (utterance_ids or "").split(",") if value.strip()]
        try:
            return store(request).subgraph(meeting_id=meeting_id, utterance_ids=ids or None)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/search")
    def search(
        request: Request,
        q: str = Query(min_length=1, max_length=500),
        meeting_id: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        state = runtime(request)
        retriever = getattr(state, "retriever", None)
        if retriever is None:
            raise HTTPException(status_code=503, detail="search is not configured")
        try:
            return retriever.retrieve(q, meeting_id=meeting_id, k=20)[0]
        except Exception as exc:
            raise error(exc) from exc

    @router.get("/api/sessions/{session_id}")
    def session(session_id: str, request: Request) -> list[dict[str, Any]]:
        try:
            return store(request).get_turns(session_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise error(exc) from exc

    @router.post("/api/ask/voice")
    async def ask_voice(
        request: Request,
        audio: UploadFile = File(...),  # noqa: B008 - FastAPI dependency marker
        session_id: str = Form("default"),
        meeting_id: str | None = Form(None),
        k: int = Form(8, ge=1, le=20),
    ) -> dict[str, Any]:
        state = runtime(request)
        assistant = agent(request)
        payload = await audio.read()
        if not payload:
            raise HTTPException(status_code=422, detail="audio must not be empty")
        try:
            text, provider = await _transcribe_question(state, payload)
            if not text.strip():
                raise HTTPException(status_code=422, detail="no speech was detected")
            result = await assistant.ask(text, session_id=session_id, meeting_id=meeting_id, k=k)
            data = result.to_dict()
            data["transcript"] = text
            data["transcript_provider"] = provider
            return data
        except HTTPException:
            raise
        except GraphError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except (AudioTooLong, ValueError, RuntimeError, NotImplementedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.websocket("/ws/meetings/{meeting_id}/audio")
    async def meeting_audio_socket(websocket: WebSocket, meeting_id: str) -> None:
        try:
            await websocket.accept()
            state = _runtime_from_websocket(websocket)
            graph: GraphStore = state.graph_store
            detail = graph.get_meeting(meeting_id)
            if detail is None:
                await websocket.close(code=4404, reason="meeting not found")
                return
            ingest: IngestPipeline | None = state.ingest_pipeline
            if ingest is None:
                await websocket.close(code=4503, reason="live ingestion is not configured")
                return
            _start_ingest(state)
            asr = getattr(state, "listener_asr", None)
            if asr is None:
                cfg = settings()
                asr = state.listener_asr = FasterWhisperASR(
                    cfg.asr_model,
                    device=cfg.asr_device,
                    compute_type=cfg.asr_compute_type,
                    language=cfg.asr_language,
                )
            speaker = getattr(state, "speaker_embedder", None) or get_speaker_embedder()
            state.speaker_embedder = speaker
            await asyncio.to_thread(ingest.flush)
            offset = max((float(u.get("t_end") or 0) for u in detail.get("utterances", [])), default=0.0)
            audio_path = settings().audio_dir / f"{meeting_id}.wav"
            session = LiveSession(
                meeting_id,
                asr,
                speaker,
                ingest.callbacks(meeting_id, time_offset_s=offset),
                threshold=settings().speaker_threshold,
                max_utterance_s=settings().max_utterance_s,
                start_seq=ingest.next_seq(meeting_id),
                recording_path=audio_path,
                speaker_state_path=settings().data_dir / "speakers" / f"{meeting_id}.json",
                vad_model_path=settings().models_dir / "silero_vad.onnx",
            )
            state.live_sessions[meeting_id] = session
            graph.set_meeting_has_audio(meeting_id, True)
            ingest.status(meeting_id, "listening", {})
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    try:
                        await asyncio.to_thread(session.feed_pcm16, message["bytes"])
                    except ListenerOverloaded as exc:
                        await websocket.send_json({"type": "error", "detail": str(exc)})
                        await websocket.close(code=4429, reason="listener overloaded")
                        break
                    await websocket.send_json({"type": "status", "state": "listening", "lag_s": session.lag_s})
                    continue
                text_message = message.get("text")
                if text_message:
                    try:
                        command = json.loads(text_message)
                    except json.JSONDecodeError:
                        command = {}
                    if command.get("type") == "stop":
                        await asyncio.to_thread(session.close)
                        if command.get("end", True):
                            await ingest.end_meeting(meeting_id, wait_final=False)
                        break
        except HTTPException:
            with contextlib.suppress(Exception):
                await websocket.close(code=4503, reason="runtime unavailable")
        except Exception as exc:  # the socket must not leak a listener thread
            log.exception("meeting audio socket failed for %s", meeting_id)
            with contextlib.suppress(Exception):
                if websocket.application_state == WebSocketState.CONNECTED:
                    await websocket.send_json({"type": "error", "detail": str(exc)})
                    await websocket.close(code=1011, reason="listener failed")
        finally:
            session = getattr(websocket.app.state, "live_sessions", {}).pop(meeting_id, None)
            if session is not None and session.running:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(session.close)

    return router


def _process_upload(
    request: Request,
    source: Path,
    meeting_id: str,
    pace: Literal["fast", "realtime"],
    recording_path: Path,
) -> None:
    state = request.app.state
    ingest: IngestPipeline = state.ingest_pipeline
    try:
        cfg: Settings = settings()
        asr = getattr(state, "listener_asr", None)
        if asr is None:
            asr = state.listener_asr = FasterWhisperASR(
                cfg.asr_model,
                device=cfg.asr_device,
                compute_type=cfg.asr_compute_type,
                language=cfg.asr_language,
            )
        speaker = getattr(state, "speaker_embedder", None) or get_speaker_embedder()
        state.speaker_embedder = speaker
        process_file(
            source,
            meeting_id,
            asr,
            speaker,
            ingest.callbacks(meeting_id),
            pace=pace,
            threshold=cfg.speaker_threshold,
            max_utterance_s=cfg.max_utterance_s,
            recording_path=recording_path,
            start_seq=ingest.next_seq(meeting_id),
        )
        ingest.status(meeting_id, "idle", {})
        state.graph_store.set_meeting_has_audio(meeting_id, True)
    except Exception as exc:  # background task: surface the failure through the event stream
        log.exception("uploaded meeting %s failed", meeting_id)
        ingest.status(meeting_id, "error", {"detail": str(exc)})
    finally:
        with contextlib.suppress(OSError):
            source.unlink()


async def _transcribe_question(state: Any, payload: bytes) -> tuple[str, str]:
    llm = getattr(state, "llm", None)
    if llm is not None and getattr(llm, "supports_audio", False):
        transcript: Transcript = await llm.transcribe(payload)
        return transcript.text.strip(), transcript.provider
    asr = getattr(state, "question_asr", None)
    if asr is None:
        cfg = settings()
        asr = state.question_asr = FasterWhisperASR(
            cfg.asr_model,
            device=cfg.asr_device,
            compute_type=cfg.asr_compute_type,
            language=cfg.asr_language,
        )
    with tempfile.NamedTemporaryFile(suffix=".wav") as temporary:
        temporary.write(payload)
        temporary.flush()
        samples = await asyncio.to_thread(decode_file, temporary.name, max_duration_s=30.0)
    text, _confidence = await asyncio.to_thread(asr.transcribe, samples)
    return text.strip(), getattr(asr, "name", "asr")


def _runtime_from_websocket(websocket: WebSocket) -> Any:
    ensure = getattr(websocket.app.state, "ensure_runtime", None)
    if ensure is not None:
        try:
            ensure()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    if getattr(websocket.app.state, "graph_store", None) is None:
        raise HTTPException(status_code=503, detail="graph storage is not configured")
    if not hasattr(websocket.app.state, "live_sessions"):
        websocket.app.state.live_sessions = {}
    return websocket.app.state


def _start_ingest(state: Any) -> None:
    """Bind the ingest writer to the current request loop exactly once."""
    pipeline = getattr(state, "ingest_pipeline", None)
    if pipeline is None:
        return
    loop = asyncio.get_running_loop()
    if getattr(state, "ingest_loop", None) is not loop:
        pipeline.start(loop)
        state.ingest_loop = loop
