"""Dependency-injected HTTP routes for the meeting orchestration agent."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .agent import MeetingAgent


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field("default", min_length=1, max_length=100)
    meeting_id: str | None = Field(None, max_length=200)
    k: int = Field(8, ge=1, le=20)


def create_router(agent: MeetingAgent) -> APIRouter:
    """Build the agent router around an already configured agent instance."""
    router = APIRouter(prefix="/api/agent", tags=["agent"])

    @router.post("/ask")
    async def ask(body: AskRequest) -> dict[str, Any]:
        result = await agent.ask(
            body.question,
            session_id=body.session_id,
            meeting_id=body.meeting_id,
            k=body.k,
        )
        return result.to_dict()

    return router
