"""HTTP application entrypoint for the On Record API."""

from __future__ import annotations

from fastapi import FastAPI

from .brand import product_name
from .event_stream import router as event_stream_router
from .events import EventBus, bus


def create_app(event_bus: EventBus | None = None) -> FastAPI:
    """Create the API application without connecting to external services."""
    app = FastAPI(title=product_name())
    app.state.event_bus = event_bus or bus
    app.include_router(event_stream_router)

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, str]:
        return {"status": "ok", "product": product_name()}

    return app


app = create_app()
