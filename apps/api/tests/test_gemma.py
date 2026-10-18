from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from wsw_brain.brain.gemma import FakeGemmaClient, GemmaClient
from wsw_brain.config import Settings


class AnswerSchema(BaseModel):
    answer: str


def _transport(responses: list[dict[str, Any]], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    iterator = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=next(iterator))

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_ollama_chat_posts_native_payload_and_returns_result() -> None:
    seen: list[httpx.Request] = []
    client = GemmaClient(
        provider="ollama",
        model="gemma4:12b-it-qat",
        base_url="http://ollama.test",
        transport=_transport([{"message": {"content": "hello"}}], seen),
    )

    result = await client.chat([{"role": "user", "content": "hi"}])

    payload = json.loads(seen[0].content)
    assert seen[0].url == "http://ollama.test/api/chat"
    assert payload == {
        "model": "gemma4:12b-it-qat",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 800},
    }
    assert result.text == "hello"
    assert result.provider == "ollama"
    assert result.model == "gemma4:12b-it-qat"


@pytest.mark.asyncio
async def test_structured_chat_retries_once_then_validates() -> None:
    seen: list[httpx.Request] = []
    client = GemmaClient(
        provider="ollama",
        model="gemma4:12b-it-qat",
        base_url="http://ollama.test",
        transport=_transport(
            [
                {"message": {"content": "not-json"}},
                {"message": {"content": '{"answer":"ok"}'}},
            ],
            seen,
        ),
    )

    result = await client.chat_json([{"role": "user", "content": "answer"}], AnswerSchema)

    assert result.answer == "ok"
    assert len(seen) == 2
    assert json.loads(seen[1].content)["format"] == "json"


@pytest.mark.asyncio
async def test_fake_client_is_deterministic_without_network() -> None:
    client = FakeGemmaClient(model="gemma4:12b-it-qat")

    first = await client.chat([{"role": "user", "content": "hello"}])
    second = await client.chat([{"role": "user", "content": "hello"}])

    assert first.text == second.text
    assert first.provider == "fake"


def test_defaults_use_12b_local_and_26b_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WSW_OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("WSW_GEMINI_MODEL", raising=False)

    settings = Settings()

    assert settings.ollama_model == "gemma4:12b-it-qat"
    assert settings.gemini_model == "gemma-4-26b-a4b-it"
