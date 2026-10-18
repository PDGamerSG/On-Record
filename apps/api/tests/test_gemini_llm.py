"""Exercise the hosted text adapter through an injected GenAI client."""

from types import SimpleNamespace
from typing import Any

import pytest

from wsw_brain.brain.llm import (
    FakeLLM,
    GeminiLLM,
    LLMError,
    _read_gemini_response,
    assistant_tool_message,
    select_llm,
    to_gemini_contents,
    tool_result_message,
)
from wsw_brain.contracts import ToolCall


def _llm() -> GeminiLLM:
    llm = GeminiLLM("test-key", "gemma-4-31b-it")
    llm._client = SimpleNamespace()
    return llm


def test_gemini_contents_preserve_system_tools_and_consecutive_results():
    call = assistant_tool_message("", [ToolCall("seek_to", {"t": 3}), ToolCall("list_items", {})])
    system, contents = to_gemini_contents(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Find the decision."},
            call,
            tool_result_message(call["tool_calls"][0], '{"ok": true}'),
            tool_result_message(call["tool_calls"][1], "[1]"),
        ]
    )

    assert system == "Be brief."
    assert [content.role for content in contents] == ["user", "model", "user"]
    assert [part.function_call.name for part in contents[1].parts] == ["seek_to", "list_items"]
    assert [part.function_response.name for part in contents[2].parts] == ["seek_to", "list_items"]
    assert contents[2].parts[1].function_response.response == {"result": [1]}


@pytest.mark.asyncio
async def test_gemini_chat_builds_config_and_skips_thought_parts():
    from google.genai import types

    calls: list[dict[str, Any]] = []

    async def generate_content(*, model: str, contents: list[Any], config: Any) -> Any:
        calls.append({"model": model, "contents": contents, "config": config})
        return types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(text="private reasoning", thought=True),
                            types.Part.from_text(text="The decision is Friday."),
                            types.Part.from_function_call(name="seek_to", args={"t": 4}),
                        ],
                    )
                )
            ]
        )

    llm = _llm()
    llm._client.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result = await llm.chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "When?"}],
        tools=[{"name": "seek_to", "description": "Seek", "parameters": {"type": "object"}}],
        json_mode=True,
        temperature=0.1,
        max_tokens=40,
    )

    config = calls[0]["config"]
    assert calls[0]["model"] == "gemma-4-31b-it"
    assert config.system_instruction == "Be brief."
    assert config.response_mime_type == "application/json"
    assert config.max_output_tokens == 40
    assert config.tools[0].function_declarations[0].name == "seek_to"
    assert result.text == "The decision is Friday."
    assert result.tool_calls == [ToolCall("seek_to", {"t": 4})]
    assert result.provider == "gemini"


@pytest.mark.asyncio
async def test_gemini_retries_once_in_compatibility_mode():
    from google.genai import errors, types

    calls: list[Any] = []

    async def generate_content(*, model: str, contents: list[Any], config: Any) -> Any:
        calls.append((contents, config))
        if len(calls) == 1:
            raise errors.ClientError(
                400,
                {"error": {"code": 400, "message": "Developer instruction is not enabled for this model"}},
            )
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text="Ready")]))]
        )

    llm = _llm()
    llm._client.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    result = await llm.chat(
        [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Ready?"}],
        json_mode=True,
    )

    assert result.text == "Ready"
    assert llm._compat is True
    assert calls[1][1].system_instruction is None
    assert calls[1][1].response_mime_type is None
    assert calls[1][0][0].parts[0].text == "Be brief."


@pytest.mark.asyncio
async def test_gemini_non_feature_error_is_not_retried():
    from google.genai import errors

    calls = 0

    async def generate_content(**kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        raise errors.ClientError(401, {"error": {"code": 401, "message": "invalid API key"}})

    llm = _llm()
    llm._client.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    with pytest.raises(LLMError, match="invalid API key"):
        await llm.chat([])
    assert calls == 1


@pytest.mark.parametrize("response_factory", [
    lambda types: types.GenerateContentResponse(candidates=[]),
    lambda types: types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[]))]
    ),
])
@pytest.mark.asyncio
async def test_gemini_rejects_empty_or_blocked_responses(response_factory):
    from google.genai import types

    llm = _llm()
    response = response_factory(types)

    async def generate_content(**kwargs: Any) -> Any:
        return response

    llm._client.aio = SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))
    with pytest.raises(LLMError, match="Gemini returned no"):
        await llm.chat([])


@pytest.mark.asyncio
async def test_gemini_rejects_malformed_tool_calls():
    response = SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            thought=False,
                            function_call=SimpleNamespace(name="seek_to", args=[1, 2]),
                            text=None,
                        )
                    ]
                )
            )
        ]
    )
    with pytest.raises(LLMError, match="tool arguments must be an object"):
        _read_gemini_response(response)


def test_gemini_settings_select_provider_before_local_probe():
    cfg = SimpleNamespace(
        llm_provider="auto",
        gemini_api_key="key",
        gemini_model="gemma-4-31b-it",
        openai_base_url=None,
        openai_api_key=None,
        ollama_url="http://ollama.test",
        ollama_model="gemma4:e4b",
    )
    called = []

    selected = select_llm(cfg, lambda *args: called.append(args))

    assert isinstance(selected, GeminiLLM)
    assert called == []


def test_explicit_gemini_requires_a_key_and_auto_can_fall_back_to_fake():
    missing = SimpleNamespace(
        llm_provider="gemini", gemini_api_key=None, gemini_model="gemma-4-31b-it",
        openai_base_url=None, openai_api_key=None, sarvam_api_key=None, ollama_url="http://ollama.test",
        ollama_model="gemma4:e4b",
    )
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        select_llm(missing)

    offline = SimpleNamespace(
        llm_provider="auto", gemini_api_key=None, gemini_model="gemma-4-31b-it",
        openai_base_url=None, openai_api_key=None, sarvam_api_key=None, ollama_url="http://ollama.test",
        ollama_model="gemma4:e4b",
    )
    assert isinstance(select_llm(offline, lambda *args: None), FakeLLM)


@pytest.mark.parametrize(("api_key", "model"), [("", "gemma"), ("key", "")])
def test_gemini_constructor_rejects_blank_settings(api_key: str, model: str):
    with pytest.raises(ValueError):
        GeminiLLM(api_key, model)


@pytest.mark.asyncio
async def test_gemini_does_not_offer_audio():
    llm = _llm()
    assert llm.supports_audio is False
    with pytest.raises(NotImplementedError, match="audio"):
        await llm.transcribe(b"wav")



PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _image_message(url: str, text: str = "Describe the whiteboard.") -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]}


@pytest.mark.parametrize("mime", ["image/png", "image/jpeg"])
def test_gemini_user_images_become_inline_data_parts(mime: str):
    import base64

    uri = f"data:{mime};base64,{base64.b64encode(PNG).decode('ascii')}"
    system, contents = to_gemini_contents([{"role": "system", "content": "Be brief."}, _image_message(uri)])

    assert system == "Be brief."
    assert [content.role for content in contents] == ["user"]
    text, image = contents[0].parts
    assert text.text == "Describe the whiteboard."
    assert image.inline_data.mime_type == mime and image.inline_data.data == PNG


@pytest.mark.parametrize(
    ("message", "error"),
    [
        (_image_message("https://example.com/board.png"), "data URIs"),
        (_image_message("data:image/gif;base64,R0lGODlh"), "data URIs"),
        ({"role": "user", "content": [{"type": "image_url", "image_url": "not-an-object"}]}, "data URIs"),
        ({"role": "user", "content": [{"type": "input_audio", "input_audio": {}}]}, "input_audio"),
    ],
)
def test_gemini_rejects_remote_images_and_unknown_parts(message: dict[str, Any], error: str):
    with pytest.raises(ValueError, match=error):
        to_gemini_contents([message])


def test_gemini_reports_image_support():
    assert _llm().supports_images is True
