"""Local text model calls behind contracts.LLM.

Assistant tool messages use {id, name, arguments} entries; tool responses keep
the matching tool_call_id. Helpers let later adapters share the same exchange.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any

import httpx

from ..contracts import LLMResult, ToolCall, Transcript

OLLAMA_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=60.0, pool=5.0)
_THOUGHT_BLOCK = re.compile(r"^\s*(?:<\|channel>thought.*?<channel\|>|<think>.*?</think>)", re.DOTALL)


class LLMError(RuntimeError):
    """A model call failed or returned an unusable response."""


def strip_thoughts(text: str) -> str:
    """Remove leading Gemma thought blocks without changing the answer itself."""
    previous = None
    while previous != text:
        previous = text
        text = _THOUGHT_BLOCK.sub("", text, count=1)
    return text.strip()


def assistant_tool_message(text: str, calls: list[ToolCall]) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {"id": f"call_{uuid.uuid4().hex[:10]}", "name": c.name, "arguments": c.arguments} for c in calls
        ],
    }


def tool_result_message(call: dict[str, Any], content: str) -> dict[str, Any]:
    return {"role": "tool", "name": call["name"], "tool_call_id": call["id"], "content": content}


def _parse_arguments(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise LLMError("Ollama returned invalid JSON tool arguments") from exc
    if not isinstance(raw, dict):
        raise LLMError("Ollama tool arguments must be a JSON object")
    return raw


class OllamaLLM:
    """Text chat and tool calls. Audio and automatic provider selection follow separately."""

    provider = "ollama"
    supports_audio = False

    def __init__(
        self, base_url: str, model: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        if not isinstance(base_url, str):
            raise TypeError("base_url must be a string")
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL as exc:
            raise ValueError("base_url must be an absolute HTTP or HTTPS URL") from exc
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._transport = transport

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [self._message(m) for m in messages],
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": self._function(t)} for t in tools]
        if json_mode:
            payload["format"] = "json"
        started = time.perf_counter()
        data = await self._post_chat(payload)
        message = data.get("message")
        if not isinstance(message, dict):
            raise LLMError("Ollama response must contain a message object")
        text = message.get("content")
        if text is None:
            text = ""
        if not isinstance(text, str):
            raise LLMError("Ollama message content must be text")
        raw_calls = message.get("tool_calls")
        if raw_calls is None:
            raw_calls = []
        if not isinstance(raw_calls, list):
            raise LLMError("Ollama tool_calls must be a list")
        calls = []
        for call in raw_calls:
            fn = call.get("function") if isinstance(call, dict) else None
            if not isinstance(fn, dict) or not isinstance(fn.get("name"), str) or not fn["name"].strip():
                raise LLMError("Ollama tool call must contain a function name")
            calls.append(ToolCall(name=fn["name"], arguments=_parse_arguments(fn.get("arguments"))))
        text = strip_thoughts(text)
        if not text and not calls:
            raise LLMError("Ollama returned no answer or tool calls")
        return LLMResult(
            text=text,
            tool_calls=calls,
            model=self.model,
            provider=self.provider,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        raise NotImplementedError("native audio is not available in the text adapter")

    @staticmethod
    def _function(tool: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
        }

    @staticmethod
    def _message(message: dict[str, Any]) -> dict[str, Any]:
        role = message["role"]
        out: dict[str, Any] = {"role": role, "content": message.get("content") or ""}
        if role == "assistant" and message.get("tool_calls"):
            out["tool_calls"] = [
                {"function": {"name": c["name"], "arguments": c.get("arguments") or {}}}
                for c in message["tool_calls"]
            ]
        elif role == "tool":
            out["tool_name"] = message.get("name", "")
        return out

    async def _post_chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/api/chat"
        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT, transport=self._transport) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 400 and "think" in response.text.lower():
                    response = await client.post(url, json={k: v for k, v in payload.items() if k != "think"})
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request to {url} failed: {exc!r}") from exc
        if response.status_code != 200:
            raise LLMError(f"Ollama {url} returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(f"Ollama returned non-JSON: {response.text[:200]}") from exc
        if not isinstance(data, dict):
            raise LLMError("Ollama response must be a JSON object")
        if data.get("error"):
            raise LLMError(f"Ollama error: {str(data['error'])[:300]}")
        return data
