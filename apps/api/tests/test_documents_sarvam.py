"""Sarvam Document AI job lifecycle and Gemma 4 through Sarvam, over HTTP mock transports."""

import io
import json
import zipfile

import httpx
import pytest

from wsw_brain.brain.llm import LLMError, SarvamLLM, select_llm
from wsw_brain.config import Settings
from wsw_brain.documents.sarvam import SarvamDocAI, SarvamError, parse_digitised_zip

BASE = "https://sarvam.test"
BLOB = "https://blob.test/out.zip?sig=abc"


def output_zip(pages: dict[int, list[dict]], markdown: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"status": "completed"}))
        for number, blocks in pages.items():
            archive.writestr(f"doc.pdf/metadata/page_{number:03d}.json",
                             json.dumps({"page_num": number, "blocks": blocks}))
        if markdown is not None:
            archive.writestr("doc.pdf/doc.md", markdown)
    return buffer.getvalue()


def lifecycle(statuses: list[dict], archive: bytes, seen: list[httpx.Request]):
    remaining = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        path = request.url.path
        if request.url.host == "blob.test":
            return httpx.Response(200, content=archive)
        if path == "/doc-ai/v1/job/digitise":
            return httpx.Response(200, json={"job_id": "job-1", "status": "pending"})
        if path == "/doc-ai/v1/job/job-1/status":
            return httpx.Response(200, json=remaining.pop(0) if len(remaining) > 1 else remaining[0])
        if path == "/doc-ai/v1/job/job-1/download-url":
            return httpx.Response(200, json={"method": "GET", "url": BLOB})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_digitise_submits_polls_downloads_and_parses_pages():
    seen: list[httpx.Request] = []
    archive = output_zip({
        2: [{"layout_tag": "paragraph", "reading_order": 1, "text": "Second page."}],
        1: [{"layout_tag": "headline", "reading_order": 1, "text": "Title"},
            {"layout_tag": "paragraph", "reading_order": 2, "text": "First page."}],
    })
    transport = lifecycle(
        [{"status": "running"}, {"status": "completed", "usage": {"pages_failed": 0}}], archive, seen
    )
    client = SarvamDocAI("key-123", BASE, poll_interval_s=0.01, transport=transport)

    result = await client.digitise("doc.pdf", b"%PDF-1.7", "application/pdf", "hi-IN")

    assert result.job_id == "job-1" and result.status == "completed"
    assert [(p.number, p.text) for p in result.pages] == [(1, "# Title\n\nFirst page."), (2, "Second page.")]
    create = seen[0]
    assert create.headers["api-subscription-key"] == "key-123"
    body = create.content.decode(errors="replace")
    assert 'name="language"' in body and "hi-IN" in body and 'name="output_format"' in body and "md" in body
    assert 'filename="doc.pdf"' in body
    download = next(r for r in seen if r.url.host == "blob.test")
    assert "api-subscription-key" not in download.headers  # the key never leaves the Sarvam host


@pytest.mark.asyncio
async def test_failed_job_reports_document_errors():
    seen: list[httpx.Request] = []
    transport = lifecycle(
        [{"status": "failed", "documents": [{"error_message": "page limit exceeded"}]}], b"", seen
    )
    client = SarvamDocAI("key", BASE, poll_interval_s=0.01, transport=transport)
    with pytest.raises(SarvamError, match="failed: page limit exceeded"):
        await client.digitise("doc.pdf", b"%PDF", "application/pdf")


@pytest.mark.asyncio
async def test_job_timeout_and_http_errors():
    seen: list[httpx.Request] = []
    slow = SarvamDocAI("key", BASE, poll_interval_s=0.01, timeout_s=0.03,
                       transport=lifecycle([{"status": "running"}], b"", seen))
    with pytest.raises(SarvamError, match="did not finish"):
        await slow.digitise("doc.pdf", b"%PDF", "application/pdf")

    def forbidden(request):
        return httpx.Response(403, json={"error": {"message": "Invalid API key"}})

    denied = SarvamDocAI("key", BASE, transport=httpx.MockTransport(forbidden))
    with pytest.raises(SarvamError, match="HTTP 403: Invalid API key"):
        await denied.digitise("doc.pdf", b"%PDF", "application/pdf")


@pytest.mark.asyncio
async def test_rate_limits_are_retried():
    calls = {"n": 0}
    seen: list[httpx.Request] = []
    inner = lifecycle([{"status": "completed"}], output_zip({1: [{"text": "Hello"}]}), seen)

    async def handler(request):
        if request.url.path.endswith("/digitise") and calls["n"] == 0:
            calls["n"] += 1
            return httpx.Response(429, headers={"retry-after": "0"}, json={"error": {"message": "slow down"}})
        return await inner.handle_async_request(request)

    client = SarvamDocAI("key", BASE, poll_interval_s=0.01, transport=httpx.MockTransport(handler))
    result = await client.digitise("doc.pdf", b"%PDF", "application/pdf")
    assert [p.text for p in result.pages] == ["Hello"]


def test_parse_falls_back_to_markdown_and_rejects_non_zip():
    assert [p.text for p in parse_digitised_zip(output_zip({}, markdown="# Only markdown"))] == ["# Only markdown"]
    with pytest.raises(SarvamError, match="not a ZIP"):
        parse_digitised_zip(b"nope")


def test_constructor_requires_key():
    with pytest.raises(ValueError):
        SarvamDocAI(" ")
    with pytest.raises(ValueError):
        SarvamLLM("")


@pytest.mark.asyncio
async def test_sarvam_llm_calls_v2_with_subscription_key_and_gemma4():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Ready."}}]})

    llm = SarvamLLM("key-9", transport=httpx.MockTransport(handler), base_url=BASE)
    result = await llm.chat([{"role": "user", "content": "Say ready"}], json_mode=True)

    assert str(requests[0].url) == f"{BASE}/v2/chat/completions"
    assert requests[0].headers["api-subscription-key"] == "key-9"
    assert "authorization" not in requests[0].headers
    payload = json.loads(requests[0].content)
    assert payload["model"] == "gemma4"
    assert payload["response_format"] == {"type": "json_object"}
    assert (result.text, result.provider, result.model) == ("Ready.", "sarvam", "gemma4")


@pytest.mark.asyncio
async def test_sarvam_llm_drops_response_format_when_prompt_asks_for_json():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    llm = SarvamLLM("key", transport=httpx.MockTransport(handler), base_url=BASE)
    await llm.chat([{"role": "system", "content": "Return strict JSON."}, {"role": "user", "content": "x"}],
                   json_mode=True)
    assert "response_format" not in json.loads(requests[0].content)


def test_select_llm_routes_sarvam():
    explicit = Settings(_env_file=None, WSW_LLM_PROVIDER="sarvam", SARVAM_API_KEY="k", WSW_SARVAM_MODEL="gemma4")
    assert isinstance(select_llm(explicit), SarvamLLM)
    auto = Settings(_env_file=None, WSW_LLM_PROVIDER="auto", SARVAM_API_KEY="k")
    assert select_llm(auto, probe=lambda *a: None).provider == "sarvam"
    with pytest.raises(LLMError, match="SARVAM_API_KEY"):
        select_llm(Settings(_env_file=None, WSW_LLM_PROVIDER="sarvam"))
