"""Exercise the local text adapter through HTTP without requiring a model server."""

import json
from copy import deepcopy

import httpx
import pytest

from wsw_brain.brain.llm import (
    FakeLLM,
    LLMError,
    OllamaLLM,
    assistant_tool_message,
    get_llm,
    probe_ollama_model,
    select_llm,
    strip_thoughts,
    tool_result_message,
)
from wsw_brain.config import Settings
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


@pytest.mark.asyncio
async def test_thinking_wording_is_treated_as_an_unsupported_think_option():
    payloads = []

    def handler(request):
        payloads.append(json.loads(request.content))
        if len(payloads) == 1:
            return httpx.Response(400, json={"error": "model does not support thinking"})
        return httpx.Response(200, json={"message": {"content": "Ready"}})

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    assert (await llm.chat([])).text == "Ready"
    assert len(payloads) == 2 and "think" not in payloads[1]


@pytest.mark.asyncio
async def test_unrelated_think_text_is_not_retried_and_original_error_is_preserved():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(400, json={"error": "model not found; did you think of another name?"})

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="did you think of another name"):
        await llm.chat([])
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_failed_think_retry_keeps_the_initial_server_error_context():
    responses = [
        httpx.Response(400, json={"error": "unsupported think option"}),
        httpx.Response(503, text="server unavailable on retry"),
    ]

    def handler(request):
        return responses.pop(0)

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="server unavailable on retry.*initial response.*unsupported think option"):
        await llm.chat([])


@pytest.mark.parametrize("retry_response", [
    httpx.Response(200, text="garbled"),
    httpx.Response(200, json={"error": "model still unavailable"}),
])
@pytest.mark.asyncio
async def test_failed_think_retry_keeps_initial_error_for_invalid_success(retry_response):
    responses = [httpx.Response(400, json={"error": "unsupported think option"}), retry_response]

    def handler(request):
        return responses.pop(0)

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="initial response.*unsupported think option"):
        await llm.chat([])


@pytest.mark.asyncio
async def test_failed_think_retry_keeps_initial_error_for_invalid_message_shape():
    responses = [
        httpx.Response(400, json={"error": "unsupported think option"}),
        httpx.Response(200, json={"message": []}),
    ]

    def handler(request):
        return responses.pop(0)

    llm = OllamaLLM("http://ollama.test", "gemma4:e4b", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMError, match="message object.*initial response.*unsupported think option"):
        await llm.chat([])


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


def test_probe_matches_exact_model_names_and_latest_alias(monkeypatch: pytest.MonkeyPatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "other:latest"}, {"name": "gemma4:latest"}, {"name": "gemma4:e4b"}]}

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: Response())

    assert probe_ollama_model("http://ollama.test/", "gemma4:e4b")["name"] == "gemma4:e4b"
    assert probe_ollama_model("http://ollama.test/", "gemma4")["name"] == "gemma4:latest"
    assert probe_ollama_model("http://ollama.test/", "missing") is None


def test_select_llm_uses_explicit_fake_without_probing():
    cfg = Settings(_env_file=None, WSW_LLM_PROVIDER="fake")
    called = []

    assert isinstance(select_llm(cfg, lambda *args: called.append(args)), FakeLLM)
    assert called == []


def test_select_llm_auto_uses_ollama_only_for_a_matching_probe():
    cfg = Settings(_env_file=None, WSW_LLM_PROVIDER="auto", WSW_OLLAMA_URL="http://ollama.test")
    selected = select_llm(cfg, lambda url, model: {"name": model})

    assert isinstance(selected, OllamaLLM)
    assert selected.base_url == "http://ollama.test"
    assert selected.model == cfg.ollama_model


def test_select_llm_auto_falls_back_to_fake_when_ollama_is_unavailable():
    cfg = Settings(_env_file=None, WSW_LLM_PROVIDER="auto")

    assert isinstance(select_llm(cfg, lambda *args: None), FakeLLM)


@pytest.mark.asyncio
async def test_fake_llm_is_deterministic_and_quotes_first_evidence_line():
    result = await FakeLLM().chat([
        {"role": "user", "content": "[u:m1:u00001] Priya: The deck is due Friday."},
    ])

    assert result.text == 'Priya said: "The deck is due Friday." [u:m1:u00001]'
    assert result.provider == "fake" and result.model == "fake"


@pytest.mark.parametrize("provider", ["gemini", "openai"])
def test_unimplemented_hosted_provider_fails_loudly(provider):
    cfg = Settings(_env_file=None, WSW_LLM_PROVIDER=provider)

    with pytest.raises(LLMError, match="not available"):
        select_llm(cfg)


def test_get_llm_caches_the_selected_provider(monkeypatch: pytest.MonkeyPatch):
    cfg = Settings(_env_file=None, WSW_LLM_PROVIDER="fake")
    monkeypatch.setattr("wsw_brain.brain.llm.settings", lambda: cfg)
    get_llm.cache_clear()
    try:
        first = get_llm()
        second = get_llm()
    finally:
        get_llm.cache_clear()

    assert isinstance(first, FakeLLM)
    assert first is second
