"""Local text model calls behind contracts.LLM.

Assistant tool messages use {id, name, arguments} entries; tool responses keep
the matching tool_call_id. Helpers let later adapters share the same exchange.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from functools import lru_cache
from typing import Any

import httpx

from ..config import Settings, settings
from ..contracts import LLM, LLMResult, ToolCall, Transcript

log = logging.getLogger(__name__)

OLLAMA_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=60.0, pool=5.0)
PROBE_TIMEOUT_S = 2.0
_THOUGHT_BLOCK = re.compile(r"^\s*(?:<\|channel>thought.*?<channel\|>|<think>.*?</think>)", re.DOTALL)
_THINK_OPTION_ERROR = re.compile(
    r"(?:\b(?:unsupported|unrecognized|unknown|invalid|unexpected)\b.{0,32}\bthink(?:ing)?\b|"
    r"\b(?:does not|doesn't)\s+support\b.{0,32}\bthink(?:ing)?\b|"
    r"\bthink(?:ing)?\b.{0,32}\b(?:unsupported|not supported|unrecognized|unknown|invalid|unexpected)\b)",
    re.IGNORECASE | re.DOTALL,
)
_EVIDENCE_LINE = re.compile(r"^\[u:([^\]]+)\]\s*(.+)$", re.MULTILINE)


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
    """Text chat and tool calls for a local model server."""

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
        initial_error: str | None = None

        def error(message: str) -> LLMError:
            if initial_error:
                message += f" (initial response: {initial_error})"
            return LLMError(message)

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT, transport=self._transport) as client:
                response = await client.post(url, json=payload)
                if (
                    response.status_code == 400
                    and "think" in payload
                    and _THINK_OPTION_ERROR.search(response.text)
                ):
                    initial_error = response.text[:300]
                    response = await client.post(url, json={k: v for k, v in payload.items() if k != "think"})
        except httpx.HTTPError as exc:
            detail = f"Ollama request to {url} failed: {exc!r}"
            if initial_error:
                detail += f" (initial response: {initial_error})"
            raise LLMError(detail) from exc
        if response.status_code != 200:
            raise error(f"Ollama {url} returned HTTP {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise error(f"Ollama returned non-JSON: {response.text[:200]}") from exc
        if not isinstance(data, dict):
            raise error("Ollama response must be a JSON object")
        if data.get("error"):
            raise error(f"Ollama error: {str(data['error'])[:300]}")
        return data


class FakeLLM:
    """Deterministic, offline text model for local development and tests."""

    provider = "fake"
    model = "fake"
    supports_audio = False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResult:
        started = time.perf_counter()
        text = "{}" if json_mode else self._answer(messages)
        return LLMResult(
            text=text,
            tool_calls=[],
            model=self.model,
            provider=self.provider,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        raise NotImplementedError("FakeLLM cannot hear audio")

    @staticmethod
    def _answer(messages: list[dict[str, Any]]) -> str:
        for message in messages:
            match = _EVIDENCE_LINE.search(message.get("content") or "")
            if match:
                uid, rest = match.group(1), match.group(2)
                who, _, said = rest.partition(": ")
                quote = said.strip() or rest.strip()
                return f'{who.strip()} said: "{quote}" [u:{uid}]'
        return "I couldn't find that in the meetings."


def probe_ollama_model(
    base_url: str, model: str, timeout: float = PROBE_TIMEOUT_S
) -> dict[str, Any] | None:
    """Return the exact model entry from the local model server, or ``None`` if unavailable."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=timeout)
        response.raise_for_status()
        models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
        log.info("Local model server at %s is not usable: %r", base_url, exc)
        return None
    wanted = {model, f"{model}:latest"} if ":" not in model else {model}
    for entry in models:
        if isinstance(entry, dict) and (entry.get("name") in wanted or entry.get("model") in wanted):
            return entry
    log.info("Local model server at %s does not have model %s", base_url, model)
    return None


def select_llm(s: Settings, probe: Any = probe_ollama_model) -> LLM:
    """Select the configured text provider without making inference requests."""
    provider = s.llm_provider
    if provider == "fake":
        return FakeLLM()
    if provider in ("gemini", "openai"):
        raise LLMError(f"configured LLM provider {provider!r} is not available in this build")
    if provider == "ollama":
        return OllamaLLM(s.ollama_url, s.ollama_model)
    if s.gemini_api_key or s.openai_base_url or s.openai_api_key:
        raise LLMError(
            "hosted LLM credentials are configured, but this build supports only local or fake text models"
        )
    try:
        available = probe(s.ollama_url, s.ollama_model)
    except Exception as exc:  # noqa: BLE001 - auto mode must remain usable offline
        log.info("Local model probe failed: %r", exc)
        available = None
    if available is not None:
        return OllamaLLM(s.ollama_url, s.ollama_model)
    log.info("no local model available; using the deterministic fake LLM")
    return FakeLLM()


@lru_cache(maxsize=1)
def get_llm() -> LLM:
    """Return the process-wide provider selected from the current settings."""
    llm = select_llm(settings())
    log.info("LLM: %s %s", llm.provider, llm.model)
    return llm
