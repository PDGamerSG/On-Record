"""HTTP application entrypoint for the On Record API."""

from __future__ import annotations

import asyncio
import threading

from fastapi import FastAPI

from .brain.agent import MeetingAgent
from .brain.agent_api import create_router as create_agent_router
from .brain.embed import get_embedder
from .brain.extract import Extractor
from .brain.llm import get_llm
from .brain.retrieve import Retriever
from .brand import product_name
from .config import settings
from .event_stream import router as event_stream_router
from .events import EventBus, bus
from .graph import GraphStore
from .meeting_api import create_router as create_meeting_router
from .pipeline import IngestPipeline


class _LazyAgent:
    """Proxy that keeps the assistant routes mounted without loading models at import time."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app

    async def ask(self, *args: object, **kwargs: object) -> object:
        _ensure_runtime(self.app, auto_configure=True)
        return await self.app.state.meeting_agent.ask(*args, **kwargs)


def create_app(
    event_bus: EventBus | None = None,
    meeting_agent: MeetingAgent | None = None,
    graph_store: GraphStore | None = None,
    ingest_pipeline: IngestPipeline | None = None,
    *,
    auto_configure: bool = True,
) -> FastAPI:
    """Create the API application.

    Runtime services are built lazily on the first live route.  Importing ``wsw_brain.app`` therefore stays
    safe for health checks and unit tests even when FalkorDB or model files are not installed.  Tests can
    inject a graph store, pipeline and agent directly.
    """
    app = FastAPI(title=product_name())
    app.state.event_bus = event_bus or bus
    app.state.graph_store = graph_store
    app.state.ingest_pipeline = ingest_pipeline
    app.state.meeting_agent = meeting_agent
    app.state.retriever = None
    app.state.llm = None
    app.state.runtime_lock = threading.Lock()
    app.state.runtime_error = None
    app.state.live_sessions = {}

    def ensure_runtime() -> None:
        _ensure_runtime(app, auto_configure=auto_configure)

    app.state.ensure_runtime = ensure_runtime
    app.include_router(event_stream_router)
    app.include_router(create_meeting_router())
    if meeting_agent is not None or auto_configure:
        app.include_router(create_agent_router(meeting_agent or _LazyAgent(app)))

    @app.on_event("shutdown")
    async def shutdown_runtime() -> None:
        pipeline = getattr(app.state, "ingest_pipeline", None)
        if pipeline is not None:
            await pipeline.aclose()
        graph = getattr(app.state, "graph_store", None)
        if graph is not None:
            graph.close()

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/health")
    def api_health() -> dict[str, bool]:
        """Return the boolean probe used by the web app to select live mode."""
        return {"ok": True}

    @app.get("/api/status")
    def status() -> dict[str, str]:
        return {"status": "ok", "product": product_name()}

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, object]:
        features = ["status", "documents", "events", "meetings", "search", "live"]
        if meeting_agent is not None or auto_configure:
            features.append("agent")
        return {
            "product": product_name(),
            "api_version": "v1",
            "features": features,
        }

    return app


def _ensure_runtime(app: FastAPI, *, auto_configure: bool) -> None:
    """Build the default graph/brain/listener stack once, on demand."""
    if not auto_configure or app.state.graph_store is not None:
        return
    with app.state.runtime_lock:
        if app.state.graph_store is not None:
            return
        cfg = settings()
        store = GraphStore(cfg.falkordb_url, cfg.graph)
        try:
            embedder = get_embedder()
            store.ensure_schema(embedder.dim)
            llm = get_llm()
            retriever = Retriever(store, embedder)
            agent = MeetingAgent(llm, retriever)
            extractor = Extractor(llm)
            pipeline = IngestPipeline(store, embedder, extractor, app.state.event_bus, cfg)
        except Exception as exc:
            app.state.runtime_error = exc
            store.close()
            raise
        app.state.graph_store = store
        app.state.retriever = retriever
        app.state.llm = llm
        app.state.meeting_agent = agent
        app.state.ingest_pipeline = pipeline


def start_ingest(app: FastAPI) -> None:
    """Start the writer thread after an async request has established its event loop."""
    pipeline = getattr(app.state, "ingest_pipeline", None)
    if pipeline is None:
        return
    loop = asyncio.get_running_loop()
    if getattr(app.state, "ingest_loop", None) is not loop:
        pipeline.start(loop)
        app.state.ingest_loop = loop


app = create_app()
