"""Standalone server for the document routes until the main application is assembled.

    uv run --project apps/api uvicorn wsw_brain.documents.app:app --port 8000

It serves only /api/documents, so the web app keeps its bundled demo meetings while the Documents page
talks to this backend.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import settings
from .api import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="On Record documents")
_origins = [o.strip() for o in settings().cors_origins.split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(router)
