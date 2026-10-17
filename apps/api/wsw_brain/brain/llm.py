"""Local text model calls behind contracts.LLM.

Assistant tool messages use {id, name, arguments} entries; tool responses keep
the matching tool_call_id. Helpers let later adapters share the same exchange.
"""

from __future__ import annotations

import asyncio
import contextlib
import heapq
import itertools
import json
import logging
import re
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

import httpx

from ..config import Settings, settings
from ..contracts import LLM, LLMResult, ToolCall, Transcript

log = logging.getLogger(__name__)

OLLAMA_TIMEOUT = httpx.Timeout(connect=5.0, read=180.0, write=60.0, pool=5.0)
PROBE_TIMEOUT_S = 2.0
_priority: ContextVar[int] = ContextVar("wsw_llm_priority", default=0)
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


@contextlib.contextmanager
def llm_priority(level: int = 1) -> Iterator[None]:
    """Mark model work as important so it moves ahead of ordinary queued questions."""
    token = _priority.set(level)
    try:
        yield
    finally:
        _priority.reset(token)


class ModelGate:
    """Bound concurrent model calls and schedule higher-priority work first."""

    def __init__(self, slots: int, max_waiting: int, wait_s: float) -> None:
        if slots < 1 or max_waiting < 0 or wait_s <= 0:
            raise ValueError("model gate limits must be positive, with max_waiting non-negative")
        self.slots = slots
        self.max_waiting = max_waiting
        self.wait_s = wait_s
        self._lock = threading.Lock()
        self._busy = 0
        self._waiters: list[tuple[int, int, asyncio.Future[None], asyncio.AbstractEventLoop]] = []
        self._sequence = itertools.count()

    @property
    def busy(self) -> int:
        return self._busy

    @property
    def waiting(self) -> int:
        return sum(1 for _, _, future, _ in self._waiters if not future.done())

    @contextlib.asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        await self._acquire()
        try:
            yield
        finally:
            self._release()

    async def _acquire(self) -> None:
        priority = _priority.get()
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._busy < self.slots and not any(not item[2].done() for item in self._waiters):
                self._busy += 1
                return
            normal_waiting = sum(
                1 for item_priority, _, future, _ in self._waiters if item_priority >= 0 and not future.done()
            )
            if priority <= 0 and normal_waiting >= self.max_waiting:
                raise LLMError("the language model is busy; try again in a moment")
            future: asyncio.Future[None] = loop.create_future()
            heapq.heappush(self._waiters, (-priority, next(self._sequence), future, loop))
        try:
            await asyncio.wait_for(future, self.wait_s)
        except BaseException as exc:
            with self._lock:
                granted = future.done() and not future.cancelled()
                future.cancel()
                self._waiters = [item for item in self._waiters if item[2] is not future]
                heapq.heapify(self._waiters)
            if granted:
                self._release()
            if isinstance(exc, TimeoutError):
                raise LLMError(f"waited {self.wait_s:.0f} s for the language model; it is busy") from None
            raise

    def _release(self) -> None:
        with self._lock:
            while self._waiters:
                _, _, future, loop = heapq.heappop(self._waiters)
                if future.done():
                    continue
                try:
                    loop.call_soon_threadsafe(self._grant, future)
                except RuntimeError:
                    continue
                return
            self._busy = max(0, self._busy - 1)

    def _grant(self, future: asyncio.Future[None]) -> None:
        if future.done():
            self._release()
        else:
            future.set_result(None)


_gates: dict[str, ModelGate] = {}
_gates_lock = threading.Lock()


def model_gate(key: str) -> ModelGate:
    """Return the process-wide gate for one model endpoint."""
    with _gates_lock:
        gate = _gates.get(key)
        if gate is None:
            cfg = settings()
            gate = _gates[key] = ModelGate(cfg.model_slots, cfg.model_max_waiting, cfg.model_queue_wait_s)
        return gate


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
            async with model_gate(self.base_url).slot(), httpx.AsyncClient(
                timeout=OLLAMA_TIMEOUT, transport=self._transport
            ) as client:
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


class GeminiLLM:
    """Gemini API text adapter with one compatibility retry for older model variants."""

    provider = "gemini"
    supports_audio = False

    def __init__(self, api_key: str, model: str) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("GeminiLLM needs an API key (GEMINI_API_KEY)")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        from google import genai

        self.model = model
        self._client = genai.Client(api_key=api_key)
        self._compat = False

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 800,
    ) -> LLMResult:
        from google.genai import errors

        started = time.perf_counter()
        try:
            response = await self._generate(messages, tools, json_mode, temperature, max_tokens)
        except errors.ClientError as exc:
            if self._compat or not _is_feature_rejection(exc):
                raise LLMError(f"Gemini API error ({self.model}): {exc}") from exc
            log.info("Gemini %s rejected advanced request options; retrying in compatibility mode", self.model)
            self._compat = True
            try:
                response = await self._generate(messages, tools, json_mode, temperature, max_tokens)
            except (errors.APIError, httpx.HTTPError) as retry_exc:
                raise LLMError(f"Gemini API error ({self.model}): {retry_exc!r}") from retry_exc
        except errors.APIError as exc:
            raise LLMError(f"Gemini API error ({self.model}): {exc}") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Gemini API request failed: {exc!r}") from exc
        text, calls = _read_gemini_response(response)
        return LLMResult(
            text=text,
            tool_calls=calls,
            model=self.model,
            provider=self.provider,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        raise NotImplementedError("Gemini text models do not provide native audio input")

    async def _generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        json_mode: bool,
        temperature: float,
        max_tokens: int,
    ) -> Any:
        from google.genai import types

        system, contents = to_gemini_contents(messages)
        if self._compat and system:
            contents.insert(0, types.Content(role="user", parts=[types.Part.from_text(text=system)]))
            contents = _merge_same_role(contents)
            system = ""
        if self._compat and json_mode:
            contents.append(
                types.Content(role="user", parts=[types.Part.from_text(text="Reply with one JSON object only.")])
            )
            contents = _merge_same_role(contents)
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            temperature=temperature,
            max_output_tokens=max_tokens,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=tool["name"],
                            description=tool.get("description", ""),
                            parameters_json_schema=tool.get("parameters")
                            or {"type": "object", "properties": {}},
                        )
                        for tool in tools
                    ]
                )
            ]
            if tools
            else None,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True) if tools else None,
            response_mime_type="application/json" if json_mode and not self._compat else None,
        )
        async with model_gate(f"gemini:{self.model}").slot():
            return await self._client.aio.models.generate_content(
                model=self.model, contents=contents, config=config
            )


def _is_feature_rejection(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(term in text for term in ("instruction", "json mode", "response_mime_type", "mime type"))


def to_gemini_contents(messages: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    """Convert contract messages into Gemini's alternating contents and system instruction."""
    from google.genai import types

    system_parts: list[str] = []
    contents: list[Any] = []
    for message in messages:
        role, text = message["role"], message.get("content") or ""
        if role == "system":
            system_parts.append(text)
        elif role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text)]))
        elif role == "assistant":
            parts = [types.Part.from_text(text=text)] if text else []
            parts.extend(
                types.Part.from_function_call(name=call["name"], args=call.get("arguments") or {})
                for call in message.get("tool_calls") or []
            )
            if parts:
                contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            try:
                result: Any = json.loads(text)
            except json.JSONDecodeError:
                result = text
            response = result if isinstance(result, dict) else {"result": result}
            part = types.Part.from_function_response(name=message.get("name", "tool"), response=response)
            contents.append(types.Content(role="user", parts=[part]))
        else:
            raise ValueError(f"unknown message role {role!r}")
    return "\n\n".join(system_parts), _merge_same_role(contents)


def _merge_same_role(contents: list[Any]) -> list[Any]:
    merged: list[Any] = []
    from google.genai import types

    for content in contents:
        if merged and merged[-1].role == content.role:
            merged[-1] = types.Content(
                role=content.role,
                parts=[*(merged[-1].parts or []), *(content.parts or [])],
            )
        else:
            merged.append(content)
    return merged


def _read_gemini_response(response: Any) -> tuple[str, list[ToolCall]]:
    texts: list[str] = []
    calls: list[ToolCall] = []
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        feedback = getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
        detail = f" ({feedback})" if feedback else ""
        raise LLMError(f"Gemini returned no candidates{detail}")
    candidate = candidates[0]
    content = getattr(candidate, "content", None)
    if content is None:
        reason = getattr(candidate, "finish_reason", None)
        detail = f" ({reason})" if reason else ""
        raise LLMError(f"Gemini returned no response content{detail}")
    for part in getattr(content, "parts", None) or []:
        if getattr(part, "thought", False):
            continue
        function_call = getattr(part, "function_call", None)
        if function_call is not None:
            name = getattr(function_call, "name", "") or ""
            args = getattr(function_call, "args", None) or {}
            if not name:
                raise LLMError("Gemini returned a tool call without a function name")
            if not isinstance(args, dict):
                raise LLMError("Gemini tool arguments must be an object")
            calls.append(ToolCall(name=name, arguments=dict(args)))
        elif getattr(part, "text", None):
            texts.append(part.text)
    text = strip_thoughts("".join(texts))
    calls = [call for call in calls if call.name]
    if not text and not calls:
        reason = getattr(candidate, "finish_reason", None)
        detail = f" ({reason})" if reason else ""
        raise LLMError(f"Gemini returned no text or tool calls{detail}")
    return text, calls


class OpenAICompatLLM:
    """OpenAI-compatible chat completions for hosted or self-hosted endpoints."""

    provider = "openai"
    supports_audio = False

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(base_url, str):
            raise TypeError("base_url must be a string")
        try:
            parsed = httpx.URL(base_url)
        except httpx.InvalidURL as exc:
            raise ValueError("base_url must be an absolute HTTP or HTTPS URL") from exc
        if parsed.scheme not in ("http", "https") or not parsed.host:
            raise ValueError("base_url must be an absolute HTTP or HTTPS URL")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model must be a non-empty string")
        base = base_url.rstrip("/")
        self.url = f"{base if parsed.path.rstrip('/').endswith('/v1') else base + '/v1'}/chat/completions"
        self.model = model
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
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
            "messages": [self._message(message) for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": OllamaLLM._function(tool)} for tool in tools]
            payload["tool_choice"] = "auto"
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        initial_error: str | None = None

        def error(message: str) -> LLMError:
            if initial_error:
                message += f" (initial response: {initial_error})"
            return LLMError(message)

        try:
            async with model_gate(self.url).slot(), httpx.AsyncClient(
                timeout=OLLAMA_TIMEOUT, transport=self._transport
            ) as client:
                response = await client.post(self.url, json=payload, headers=self._headers)
                retry_payload = self._compatibility_payload(payload, response)
                if retry_payload is not None:
                    initial_error = response.text[:300]
                    response = await client.post(self.url, json=retry_payload, headers=self._headers)
        except httpx.HTTPError as exc:
            raise error(f"OpenAI-compatible request to {self.url} failed: {exc!r}") from exc
        if response.status_code != 200:
            raise error(
                f"OpenAI-compatible {self.url} returned HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise error(f"OpenAI-compatible returned non-JSON: {response.text[:200]}") from exc
        if not isinstance(data, dict):
            raise error("OpenAI-compatible response must be a JSON object")
        if data.get("error"):
            detail = data["error"]
            if isinstance(detail, dict):
                detail = detail.get("message") or detail
            raise error(f"OpenAI-compatible error: {str(detail)[:300]}")
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise error("OpenAI-compatible response must contain a choices array")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise error("OpenAI-compatible choice must contain a message object")
        text = message.get("content") or ""
        if not isinstance(text, str):
            raise error("OpenAI-compatible message content must be text")
        calls = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise error("OpenAI-compatible tool_calls must be a list")
        for raw_call in raw_calls:
            function = raw_call.get("function") if isinstance(raw_call, dict) else None
            if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not function["name"].strip():
                raise error("OpenAI-compatible tool call must contain a function name")
            raw_arguments = function.get("arguments")
            if raw_arguments in (None, ""):
                arguments = {}
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            elif isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except ValueError as exc:
                    raise error("OpenAI-compatible tool arguments are not valid JSON") from exc
                if not isinstance(arguments, dict):
                    raise error("OpenAI-compatible tool arguments must be a JSON object")
            else:
                raise error("OpenAI-compatible tool arguments must be a JSON object")
            calls.append(ToolCall(name=function["name"], arguments=arguments))
        text = strip_thoughts(text)
        if not text and not calls:
            raise error("OpenAI-compatible returned no answer or tool calls")
        return LLMResult(
            text=text,
            tool_calls=calls,
            model=self.model,
            provider=self.provider,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _compatibility_payload(payload: dict[str, Any], response: httpx.Response) -> dict[str, Any] | None:
        """Drop only optional controls named by a client-side feature rejection, once."""
        if response.status_code not in (400, 422):
            return None
        text = response.text.lower()
        retry = dict(payload)
        if "response_format" in payload and (
            "response_format" in text or "json mode" in text or "structured output" in text
        ):
            retry.pop("response_format", None)
        if "tool_choice" in payload and (
            "tool_choice" in text or "function calling" in text or "tool use" in text
        ):
            retry.pop("tool_choice", None)
        return retry if retry != payload else None

    async def transcribe(self, wav_bytes: bytes, *, hint: str | None = None) -> Transcript:
        raise NotImplementedError("audio questions are not routed through the OpenAI-compatible adapter")

    @staticmethod
    def _message(message: dict[str, Any]) -> dict[str, Any]:
        role = message["role"]
        if role == "assistant" and message.get("tool_calls"):
            return {
                "role": "assistant",
                "content": message.get("content") or None,
                "tool_calls": [
                    {
                        "id": call.get("id") or f"call_{index}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments") or {}, separators=(",", ":")),
                        },
                    }
                    for index, call in enumerate(message["tool_calls"])
                ],
            }
        if role == "tool":
            return {
                "role": "tool",
                "tool_call_id": message.get("tool_call_id") or message.get("name", ""),
                "content": message.get("content") or "",
            }
        return {"role": role, "content": message.get("content") or ""}


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
    if provider == "gemini" or (provider == "auto" and s.gemini_api_key):
        if not s.gemini_api_key:
            raise LLMError("configured Gemini provider needs GEMINI_API_KEY")
        return GeminiLLM(s.gemini_api_key, s.gemini_model)
    if provider == "openai":
        if not s.openai_base_url:
            raise LLMError("configured OpenAI-compatible provider needs WSW_OPENAI_BASE_URL")
        return OpenAICompatLLM(s.openai_base_url, s.openai_api_key, s.openai_model)
    if provider == "ollama":
        return OllamaLLM(s.ollama_url, s.ollama_model)
    if s.gemini_api_key or s.openai_base_url or s.openai_api_key:
        raise LLMError(
            "hosted credentials are configured; set WSW_LLM_PROVIDER to gemini or openai explicitly"
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
