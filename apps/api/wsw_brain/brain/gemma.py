"""Provider-neutral Gemma client for local and hosted runtime checks.

Ollama is the primary local runtime. The client deliberately uses Ollama's native
``/api/chat`` endpoint so thinking can be disabled and JSON mode can be requested
without depending on an OpenAI compatibility layer.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import Settings
from ..contracts import LLMResult, ToolCall, Transcript

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Base class for model transport and response failures."""


class LLMConfigurationError(LLMError):
    """The selected provider is missing required configuration."""


class LLMResponseError(LLMError):
    """The provider returned a response that could not be used."""


def _latency_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _strip_thoughts(text: str) -> str:
    for opening, closing in (("<think>", "</think>"), ("<|channel|>thought", "<|channel|>")):
        while opening in text and closing in text:
            before, rest = text.split(opening, 1)
            _, after = rest.split(closing, 1)
            text = before + after
    return text.strip()


def _json_text(text: str) -> Any:
    cleaned = _strip_thoughts(text).strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().lower() in {"```json", "```"}:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMResponseError("model returned invalid JSON") from exc


def _tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        name = function.get("name") or item.get("name")
        if not name:
            continue
        arguments = function.get("arguments", item.get("arguments", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {"_raw": arguments}
        calls.append(ToolCall(name=str(name), arguments=arguments if isinstance(arguments, dict) else {}))
    return calls


class GemmaClient:
    """Async Gemma client for Ollama, Gemini REST, and OpenAI-compatible endpoints."""

    supports_audio = False

    def __init__(
        self,
        provider: str,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        timeout_s: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if provider not in {"ollama", "gemini", "openai"}:
            raise LLMConfigurationError(f"unsupported provider: {provider}")
        if not model.strip():
            raise LLMConfigurationError("model must be a non-empty string")
        if provider in {"gemini", "openai"} and not api_key:
            raise LLMConfigurationError(f"{provider} requires an API key")
        if provider == "openai" and not base_url:
            raise LLMConfigurationError("openai requires a base URL")
        self.provider = provider
        self.model = model
        self.base_url = (base_url or "http://127.0.0.1:11434").rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._transport = transport
        self.supports_audio = provider == "ollama" and self._ollama_audio_model(model)

    @staticmethod
    def _ollama_audio_model(model: str) -> bool:
        lowered = model.lower()
        return lowered in {"gemma4", "gemma4:latest"} or any(
            marker in lowered for marker in ("gemma4:e2b", "gemma4:e4b", "gemma4:12b")
        )

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
        if self.provider == "ollama":
            data = await self._ollama_chat(messages, tools, json_mode, temperature, max_tokens)
            message = data.get("message") or {}
            return LLMResult(
                text=_strip_thoughts(str(message.get("content") or "")),
                tool_calls=_tool_calls(message),
                model=self.model,
                provider=self.provider,
                latency_ms=_latency_ms(started),
            )
        data = await self._hosted_chat(messages, tools, json_mode, temperature, max_tokens)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return LLMResult(
            text=_strip_thoughts(str(message.get("content") or "")),
            tool_calls=_tool_calls(message),
            model=self.model,
            provider=self.provider,
            latency_ms=_latency_ms(started),
        )

    async def chat_json(self, messages: list[dict[str, Any]], schema: type[T], *, max_tokens: int = 800) -> T:
        last_error: Exception | None = None
        current = list(messages)
        for attempt in range(2):
            result = await self.chat(current, json_mode=True, temperature=0.0, max_tokens=max_tokens)
            try:
                return schema.model_validate(_json_text(result.text))
            except (LLMResponseError, ValidationError) as exc:
                last_error = exc
                if attempt == 0:
                    current = [
                        *messages,
                        {
                            "role": "user",
                            "content": "Return only valid JSON matching the requested schema. Repair your previous response.",
                        },
                    ]
        raise LLMResponseError(f"model response did not match {schema.__name__}") from last_error

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        if not self.supports_audio:
            raise LLMConfigurationError(f"{self.provider} model {self.model!r} does not support native audio")
        prompt = "Transcribe this audio exactly. Return only the spoken words."
        if hint:
            prompt += f" Use these names for spelling hints: {hint}."
        started = time.perf_counter()
        data = await self._ollama_chat(
            [{"role": "user", "content": prompt, "images": [base64.b64encode(wav_bytes).decode("ascii")]}],
            None,
            False,
            0.0,
            256,
        )
        text = _strip_thoughts(str((data.get("message") or {}).get("content") or ""))
        if not text:
            raise LLMResponseError("model returned an empty transcript")
        return Transcript(text=text, model=self.model, provider="gemma4-audio:ollama", latency_ms=_latency_ms(started))

    async def health(self) -> dict[str, Any]:
        if self.provider == "ollama":
            url = f"{self.base_url}/api/tags"
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    models = response.json().get("models") or []
            except (httpx.HTTPError, ValueError) as exc:
                raise LLMError("Ollama health check failed") from exc
            names = [item.get("name") or item.get("model") for item in models]
            return {"ok": True, "provider": self.provider, "model": self.model, "available": self.model in names}
        return {"ok": True, "provider": self.provider, "model": self.model, "available": True}

    async def _ollama_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["format"] = "json"
        return await self._post_json(f"{self.base_url}/api/chat", payload)

    async def _hosted_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        if self.provider == "gemini":
            contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m.get("content", "")}]} for m in messages]
            payload: dict[str, Any] = {
                "contents": contents,
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
            }
            if json_mode:
                payload["generationConfig"]["responseMimeType"] = "application/json"
            url = f"{self.base_url}/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            data = await self._post_json(url, payload)
            text = ""
            for candidate in data.get("candidates") or []:
                for part in (candidate.get("content") or {}).get("parts") or []:
                    if part.get("text"):
                        text += part["text"]
            return {"choices": [{"message": {"content": text}}]}
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return await self._post_json(f"{self.base_url}/chat/completions", payload, auth=True)

    async def _post_json(self, url: str, payload: dict[str, Any], *, auth: bool = False) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if auth and self.api_key else None
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, transport=self._transport) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError(f"{self.provider} request failed") from exc
        if not isinstance(data, dict) or data.get("error"):
            raise LLMResponseError(f"{self.provider} returned an unusable response")
        return data


class FakeGemmaClient:
    """Deterministic client used by tests and the offline benchmark."""

    provider = "fake"
    supports_audio = False

    def __init__(self, model: str = "fake") -> None:
        self.model = model

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResult:
        del tools, temperature, max_tokens
        text = json.dumps({"answer": "offline fake response"}) if json_mode else "offline fake response"
        return LLMResult(text=text, tool_calls=[], model=self.model, provider=self.provider, latency_ms=0.0)

    async def chat_json(self, messages: list[dict[str, Any]], schema: type[T], *, max_tokens: int = 800) -> T:
        del messages, max_tokens
        return schema.model_validate({"answer": "offline fake response"})

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        del wav_bytes, hint
        raise LLMConfigurationError("fake provider cannot transcribe audio")

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.provider, "model": self.model, "available": True}


def make_client(settings: Settings) -> GemmaClient | FakeGemmaClient:
    """Build the configured client; ``auto`` chooses Gemini, then Ollama, then fake."""
    provider = settings.llm_provider
    if provider == "fake":
        return FakeGemmaClient("fake")
    if provider == "auto":
        if settings.gemini_api_key:
            provider = "gemini"
        elif _ollama_has_model(settings.ollama_url, settings.ollama_model):
            provider = "ollama"
        else:
            return FakeGemmaClient("fake")
    if provider == "ollama":
        return GemmaClient("ollama", settings.ollama_model, settings.ollama_url)
    if provider == "gemini":
        return GemmaClient("gemini", settings.gemini_model, "https://generativelanguage.googleapis.com", settings.gemini_api_key)
    if provider == "openai":
        return GemmaClient("openai", settings.openai_model, settings.openai_base_url, settings.openai_api_key)
    raise LLMConfigurationError(f"unsupported provider: {provider}")


def _ollama_has_model(base_url: str, model: str) -> bool:
    """Probe Ollama without raising or logging credentials; used only by ``auto`` startup routing."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=1.0)
        response.raise_for_status()
        models = response.json().get("models") or []
    except (httpx.HTTPError, ValueError):
        return False
    names = {item.get("name") or item.get("model") for item in models}
    return model in names or (":" not in model and f"{model}:latest" in names)
