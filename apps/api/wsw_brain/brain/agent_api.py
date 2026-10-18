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


class AskResponse(BaseModel):
    """Stable JSON contract returned by the orchestration endpoint."""

    answer: str
    citations: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    cypher: list[str]
    model: str
    provider: str
    session_id: str
    timings: dict[str, float]
    transcript: str | None = None
    transcript_provider: str | None = None


def create_router(agent: MeetingAgent) -> APIRouter:
    """Build the agent router around an already configured agent instance."""
    router = APIRouter(tags=["agent"])

    @router.post("/api/agent/ask", response_model=AskResponse)
    @router.post("/api/ask", response_model=AskResponse, include_in_schema=False)
    async def ask(body: AskRequest) -> AskResponse:
        result = await agent.ask(
            body.question,
            session_id=body.session_id,
            meeting_id=body.meeting_id,
            k=body.k,
        )
        return AskResponse.model_validate(result.to_dict())

    return router
