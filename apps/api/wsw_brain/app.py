"""HTTP application entrypoint for the On Record API."""

from __future__ import annotations

from fastapi import FastAPI

from .brand import product_name


def create_app() -> FastAPI:
    """Create the API application without connecting to external services."""
    app = FastAPI(title=product_name())

    @app.get("/healthz", include_in_schema=False)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/status")
    def status() -> dict[str, str]:
        return {"status": "ok", "product": product_name()}

    return app


app = create_app()
