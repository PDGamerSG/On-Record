"""Exercise the local text adapter through HTTP without requiring a model server."""

import json
from copy import deepcopy

import httpx
import pytest

from wsw_brain.brain.llm import (
    LLMError,
    OllamaLLM,
    assistant_tool_message,
    strip_thoughts,
    tool_result_message,
)
from wsw_brain.contracts import ToolCall


@pytest.mark.asyncio
async def test_chat_formats_options_and_preserves_model_metadata():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {"content": "<think>considering</think> The deck is due Friday."}})

    llm = OllamaLLM("http://ollama.test/", "gemma4:e4b", transport=httpx.MockTransport(handler))
    result = await llm.chat(
        [{"role": "user", "content": "When is the deck due?"}],
        json_mode=True,
        temperature=0.1,
        max_tokens=50,
    )

    assert str(requests[0].url) == "http://ollama.test/api/chat"
    assert json.loads(requests[0].content) == {
        "model": "gemma4:e4b",
        "messages": [{"role": "user", "content": "When is the deck due?"}],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0.1, "num_predict": 50},
    }
    assert result.text == "The deck is due Friday."
    assert result.tool_calls == []
    assert result.provider == "ollama" and result.model == "gemma4:e4b"
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_tool_exchange_round_trips_dict_and_json_arguments_without_mutating_messages():
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {
            "content": "",
            "tool_calls": [
                {"function": {"name": "seek_to", "arguments": '{"t": 12}'}},
                {"function": {"name": "list_action_items", "arguments": {"owner": "Priya"}}},
            ],
        }})

    assistant = assistant_tool_message("Checking.", [ToolCall("list_action_items", {"owner": "Priya"})])
    call = assistant["tool_calls"][0]
    messages = [
        {"role": "user", "content": "Show Priya's items."},
        assistant,
        tool_result_message(call, '{"items": []}'),
    ]
    original = deepcopy(messages)
    tools = [{"name": "seek_to", "description": "Seek to a moment", "parameters": {
        "type": "object", "properties": {"t": {"type": "number"}},
    }}]
    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    result = await llm.chat(messages, tools=tools)

    assert result.tool_calls == [ToolCall("seek_to", {"t": 12}), ToolCall("list_action_items", {"owner": "Priya"})]
    assert result.text == ""
    assert payloads[0]["tools"] == [{"type": "function", "function": tools[0]}]
    assert payloads[0]["messages"][1] == {"role": "assistant", "content": "Checking.", "tool_calls": [
        {"function": {"name": "list_action_items", "arguments": {"owner": "Priya"}}},
    ]}
    assert payloads[0]["messages"][2] == {"role": "tool", "content": '{"items": []}', "tool_name": "list_action_items"}
    assert messages == original
    assert call["id"] and messages[2]["tool_call_id"] == call["id"]


@pytest.mark.asyncio
async def test_tool_with_no_arguments_gets_an_empty_object():
    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json={"message": {"tool_calls": [{"function": {"name": "list_decisions"}}]}})
    ))
    assert (await llm.chat([])).tool_calls == [ToolCall("list_decisions", {})]


@pytest.mark.asyncio
async def test_unsupported_thinking_option_is_retried_once_without_changing_caller_messages():
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "This model does not support THINK"})
        return httpx.Response(200, json={"message": {"content": "Ready"}})

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    assert (await llm.chat([])).text == "Ready"
    assert len(payloads) == 2
    first = dict(payloads[0])
    assert first.pop("think") is False
    assert payloads[1] == first


@pytest.mark.parametrize(("status", "body", "expected_requests"), [
    (400, "unsupported think option", 2),
    (400, "invalid model", 1),
    (500, "server failure", 1),
])
@pytest.mark.asyncio
async def test_http_errors_are_wrapped_and_never_retried_indefinitely(status, body, expected_requests):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text=body)

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match=f"HTTP {status}"):
        await llm.chat([])
    assert len(requests) == expected_requests


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadTimeout])
@pytest.mark.asyncio
async def test_network_and_timeout_errors_use_the_public_error_type(error):
    def handler(request):
        raise error("server unavailable", request=request)

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="request.*failed") as raised:
        await llm.chat([])
    assert isinstance(raised.value.__cause__, error)


@pytest.mark.parametrize("data", [
    [], None, {},
    {"error": "model unavailable"},
    {"message": []},
    {"message": {"content": 42}},
    {"message": {"content": "", "tool_calls": []}},
    {"message": {"tool_calls": "invalid"}},
    {"message": {"tool_calls": [None]}},
    {"message": {"tool_calls": [{"function": None}]}},
    {"message": {"tool_calls": [{"function": {"name": ""}}]}},
    {"message": {"tool_calls": [{"function": {"name": "seek_to", "arguments": "not json"}}]}},
    {"message": {"tool_calls": [{"function": {"name": "seek_to", "arguments": "[]"}}]}},
    {"message": {"tool_calls": [{"function": {"name": "seek_to", "arguments": [12]}}]}},
])
@pytest.mark.asyncio
async def test_malformed_success_responses_raise_model_errors(data):
    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=json.dumps(data), headers={"content-type": "application/json"})
    ))
    with pytest.raises(LLMError):
        await llm.chat([])


@pytest.mark.asyncio
async def test_non_json_response_raises_model_error():
    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text="model server restarted")
    ))
    with pytest.raises(LLMError, match="non-JSON"):
        await llm.chat([])


@pytest.mark.parametrize(("base_url", "model"), [
    ("", "gemma4:e4b"), ("localhost:11434", "gemma4:e4b"), ("ftp://localhost", "gemma4:e4b"),
    ("http://localhost:11434", ""), ("http://localhost:11434", "  "),
])
def test_invalid_connection_settings_are_rejected_before_requesting(base_url, model):
    with pytest.raises(ValueError):
        OllamaLLM(base_url, model)


@pytest.mark.parametrize(("text", "expected"), [
    ("<|channel>thought\nhmm<channel|>Answer", "Answer"),
    ("<think>one</think> <think>two</think> Hello", "Hello"),
    ("  Answer with a <think>literal example</think>  ", "Answer with a <think>literal example</think>"),
])
def test_leading_thought_blocks_are_removed_without_rewriting_answer_text(text, expected):
    assert strip_thoughts(text) == expected


@pytest.mark.asyncio
async def test_text_adapter_explicitly_reports_audio_as_unavailable():
    llm = OllamaLLM("http://ollama.test", "gemma4:e4b")
    assert llm.supports_audio is False
    with pytest.raises(NotImplementedError, match="audio"):
        await llm.transcribe(b"audio")
