"""HTTP application entrypoint for the On Record API."""

from __future__ import annotations

from fastapi import FastAPI

from .brain.agent import MeetingAgent
from .brand import product_name
from .events import EventBus, bus
from .routes.agent import create_router as create_agent_router
from .routes.event_stream import router as event_stream_router


def create_app(event_bus: EventBus | None = None, meeting_agent: MeetingAgent | None = None) -> FastAPI:
    """Create the API application without connecting to external services."""
    app = FastAPI(title=product_name())
    app.state.event_bus = event_bus or bus
    app.include_router(event_stream_router)
    if meeting_agent is not None:
        app.include_router(create_agent_router(meeting_agent))

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
        features = ["status", "documents", "events"]
        if meeting_agent is not None:
            features.append("agent")
        return {
            "product": product_name(),
            "api_version": "v1",
            "features": features,
        }

    return app


app = create_app()
