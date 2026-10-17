"""Exercise OpenAI-compatible chat through an HTTP mock transport."""

import json
from copy import deepcopy

import httpx
import pytest

from wsw_brain.brain.llm import (
    LLMError,
    OpenAICompatLLM,
    assistant_tool_message,
    select_llm,
    tool_result_message,
)
from wsw_brain.contracts import ToolCall


def test_openai_constructor_normalizes_v1_endpoint_and_auth_header():
    llm = OpenAICompatLLM("https://inference.example/v1/", "secret", "gemma-4-31B-it")

    assert llm.url == "https://inference.example/v1/chat/completions"
    assert llm._headers == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_openai_chat_builds_payload_and_parses_text_and_tools():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "<think>private</think> Ready.",
                            "tool_calls": [
                                {"function": {"name": "seek_to", "arguments": '{"t": 12}'}}
                            ],
                        }
                    }
                ]
            },
        )

    llm = OpenAICompatLLM(
        "https://inference.example/v1", "secret", "gemma-4-31B-it", transport=httpx.MockTransport(handler)
    )
    result = await llm.chat(
        [{"role": "user", "content": "Find it."}],
        tools=[{"name": "seek_to", "description": "Seek", "parameters": {"type": "object"}}],
        json_mode=True,
        temperature=0.1,
        max_tokens=40,
    )

    payload = json.loads(requests[0].content)
    assert str(requests[0].url) == "https://inference.example/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer secret"
    assert payload["model"] == "gemma-4-31B-it"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["tool_choice"] == "auto"
    assert payload["tools"][0]["function"]["name"] == "seek_to"
    assert result.text == "Ready."
    assert result.tool_calls == [ToolCall("seek_to", {"t": 12})]
    assert result.provider == "openai"


@pytest.mark.asyncio
async def test_openai_tool_exchange_preserves_ids_and_does_not_mutate_messages():
    call = assistant_tool_message("Checking.", [ToolCall("seek_to", {"t": 5})])
    messages = [
        {"role": "user", "content": "Go there."},
        call,
        tool_result_message(call["tool_calls"][0], '{"ok": true}'),
    ]
    original = deepcopy(messages)
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "Done"}}]})

    llm = OpenAICompatLLM("https://inference.example", None, "model", transport=httpx.MockTransport(handler))
    result = await llm.chat(messages)

    sent = payloads[0]["messages"]
    assert sent[1]["tool_calls"][0]["id"] == call["tool_calls"][0]["id"]
    assert sent[1]["tool_calls"][0]["function"]["arguments"] == '{"t":5}'
    assert sent[2]["tool_call_id"] == call["tool_calls"][0]["id"]
    assert messages == original
    assert result.text == "Done"


@pytest.mark.parametrize("data", [
    [], None, {}, {"error": {"message": "quota exceeded"}},
    {"choices": []}, {"choices": [{}]}, {"choices": [{"message": []}]},
    {"choices": [{"message": {"content": 3}}]},
    {"choices": [{"message": {"tool_calls": "bad"}}]},
    {"choices": [{"message": {"tool_calls": [{"function": {"name": ""}}]}}]},
    {"choices": [{"message": {"tool_calls": [{"function": {"name": "seek", "arguments": "[]"}}]}}]},
])
@pytest.mark.asyncio
async def test_openai_malformed_successes_raise_llm_error(data):
    llm = OpenAICompatLLM(
        "https://inference.example", None, "model",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps(data), headers={"content-type": "application/json"})
        ),
    )

    with pytest.raises(LLMError):
        await llm.chat([])


@pytest.mark.asyncio
async def test_openai_http_and_network_errors_are_wrapped():
    failing = OpenAICompatLLM(
        "https://inference.example", None, "model",
        transport=httpx.MockTransport(lambda request: httpx.Response(429, text="slow down")),
    )
    with pytest.raises(LLMError, match="HTTP 429"):
        await failing.chat([])

    network = OpenAICompatLLM(
        "https://inference.example", None, "model",
        transport=httpx.MockTransport(lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=request))),
    )
    with pytest.raises(LLMError, match="request.*failed"):
        await network.chat([])


@pytest.mark.parametrize(("base_url", "model"), [
    ("", "model"), ("localhost:8080", "model"), ("ftp://host", "model"), ("https://host", ""),
])
def test_openai_constructor_rejects_invalid_connection_settings(base_url, model):
    with pytest.raises((TypeError, ValueError)):
        OpenAICompatLLM(base_url, None, model)


def test_explicit_openai_provider_selects_the_adapter():
    config = type(
        "Config",
        (),
        {
            "llm_provider": "openai",
            "openai_base_url": "https://inference.example/v1",
            "openai_api_key": "secret",
            "openai_model": "model",
            "gemini_api_key": None,
            "ollama_url": "http://ollama.test",
            "ollama_model": "gemma4:e4b",
        },
    )()

    selected = select_llm(config)

    assert isinstance(selected, OpenAICompatLLM)
    assert selected.url == "https://inference.example/v1/chat/completions"

