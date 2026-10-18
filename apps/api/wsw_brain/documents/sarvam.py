"""Sarvam Document AI (Sarvam Vision) digitisation: create a job, wait for it, read the pages back.

One call handles one part of at most 10 pages (see split.py). The job lifecycle is:
POST /doc-ai/v1/job/digitise -> GET /doc-ai/v1/job/{id}/status (until terminal) ->
GET /doc-ai/v1/job/{id}/download-url -> GET the ZIP, which holds metadata/page_NNN.json per page.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import httpx

from .split import Page, page_text

log = logging.getLogger(__name__)

SARVAM_BASE_URL = "https://api.sarvam.ai"
TERMINAL = frozenset({"completed", "partially_completed", "failed", "rejected"})
USABLE = frozenset({"completed", "partially_completed"})
_RETRY_STATUS = frozenset({429, 502, 503, 504})
_PAGE_FILE = re.compile(r"(?:^|/)metadata/page_(\d+)\.json$")
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=10.0)


class SarvamError(RuntimeError):
    """A Sarvam request failed, a job did not finish, or its output was unusable."""


@dataclass(frozen=True)
class DigitisedPart:
    """Output of one digitise job. Page numbers are 1-based within the uploaded part."""

    job_id: str
    status: str
    pages: list[Page]
    pages_failed: int = 0
    timings: dict[str, float] = field(default_factory=dict)
    visual_description: str = ""  # Gemma 4's description of an uploaded image, if one was made


class SarvamDocAI:
    """Async client for Document AI digitisation. The API key is only sent to `base_url`."""

    def __init__(
        self,
        api_key: str,
        base_url: str = SARVAM_BASE_URL,
        *,
        poll_interval_s: float = 2.0,
        timeout_s: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("a Sarvam API key is required (set SARVAM_API_KEY)")
        if poll_interval_s <= 0 or timeout_s <= 0:
            raise ValueError("poll_interval_s and timeout_s must be positive")
        self.base_url = base_url.rstrip("/")
        self._headers = {"api-subscription-key": api_key.strip()}
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._transport = transport

    async def digitise(
        self, filename: str, data: bytes, content_type: str, language: str = "en-IN"
    ) -> DigitisedPart:
        """Digitise one part and return its pages. Raises SarvamError if the job fails or times out."""
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport) as client:
            created = await self._request(
                client,
                "POST",
                "/doc-ai/v1/job/digitise",
                files={"file": (filename, data, content_type)},
                data={"language": language, "output_format": "md"},
            )
            job_id = created.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise SarvamError(f"Document AI did not return a job id: {str(created)[:200]}")
            submitted = time.perf_counter()
            status = await self._wait(client, job_id)
            finished = time.perf_counter()
            state = str(status.get("status", "")).lower()
            usage = status.get("usage") if isinstance(status.get("usage"), dict) else {}
            if state not in USABLE:
                raise SarvamError(f"Document AI job {job_id} ended as {state or 'unknown'}: {_job_errors(status)}")
            link = await self._request(client, "GET", f"/doc-ai/v1/job/{job_id}/download-url")
            url = link.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                raise SarvamError(f"Document AI job {job_id} returned no download URL")
            archive = await self._download(url)
        pages = parse_digitised_zip(archive)
        if not pages:
            raise SarvamError(f"Document AI job {job_id} produced no readable pages")
        log.info("digitised %s: %d pages in %.1fs (job %s, %s)", filename, len(pages),
                 time.perf_counter() - started, job_id, state)
        return DigitisedPart(
            job_id=job_id,
            status=state,
            pages=pages,
            pages_failed=int(usage.get("pages_failed") or 0),
            timings={
                "submit_s": round(submitted - started, 2),
                "process_s": round(finished - submitted, 2),
                "total_s": round(time.perf_counter() - started, 2),
            },
        )

    async def _wait(self, client: httpx.AsyncClient, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_s
        while True:
            status = await self._request(client, "GET", f"/doc-ai/v1/job/{job_id}/status")
            if str(status.get("status", "")).lower() in TERMINAL:
                return status
            if time.monotonic() >= deadline:
                raise SarvamError(f"Document AI job {job_id} did not finish within {self.timeout_s:.0f}s")
            await asyncio.sleep(self.poll_interval_s)

    async def _request(self, client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        for attempt in range(3):
            try:
                response = await client.request(method, url, headers=self._headers, **kwargs)
            except httpx.HTTPError as exc:
                if attempt == 2:
                    raise SarvamError(f"Sarvam request {method} {path} failed: {exc!r}") from exc
                await asyncio.sleep(0.5 * 2**attempt)
                continue
            if response.status_code in _RETRY_STATUS and attempt < 2:
                await asyncio.sleep(_retry_after(response, 0.5 * 2**attempt))
                continue
            if response.status_code >= 400:
                raise SarvamError(f"Sarvam {method} {path} returned HTTP {response.status_code}: "
                                  f"{_error_detail(response)}")
            try:
                body = response.json()
            except ValueError as exc:
                raise SarvamError(f"Sarvam {method} {path} returned non-JSON: {response.text[:200]}") from exc
            if not isinstance(body, dict):
                raise SarvamError(f"Sarvam {method} {path} returned an unexpected body")
            return body
        raise AssertionError("unreachable")

    async def _download(self, url: str) -> bytes:
        # Signed storage URL: no Sarvam credentials on this request.
        async with httpx.AsyncClient(timeout=_TIMEOUT, transport=self._transport, follow_redirects=True) as client:
            try:
                response = await client.get(url)
            except httpx.HTTPError as exc:
                raise SarvamError(f"downloading Document AI output failed: {exc!r}") from exc
        if response.status_code != 200:
            raise SarvamError(f"downloading Document AI output returned HTTP {response.status_code}")
        return response.content


def parse_digitised_zip(archive: bytes) -> list[Page]:
    """Pages from a digitise output ZIP, using per-page layout blocks; falls back to the Markdown file."""
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            names = bundle.namelist()
            pages: dict[int, Page] = {}
            for name in names:
                match = _PAGE_FILE.search(name)
                if not match:
                    continue
                try:
                    meta = json.loads(bundle.read(name))
                except ValueError:
                    log.warning("skipping unreadable page metadata %s", name)
                    continue
                number = int(meta.get("page_num") or match.group(1))
                blocks = meta.get("blocks") if isinstance(meta.get("blocks"), list) else []
                pages[number] = Page(number, page_text(blocks))
            if pages:
                return [pages[n] for n in sorted(pages)]
            markdown = [n for n in names if PurePosixPath(n).suffix.lower() == ".md"]
            if markdown:
                return [Page(1, bundle.read(markdown[0]).decode("utf-8", errors="replace").strip())]
    except zipfile.BadZipFile as exc:
        raise SarvamError(f"Document AI output is not a ZIP archive: {exc}") from exc
    return []


def _retry_after(response: httpx.Response, default: float) -> float:
    try:
        return min(float(response.headers.get("retry-after", default)), 10.0)
    except ValueError:
        return default


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)[:300]
        if error or body.get("detail") or body.get("message"):
            return str(error or body.get("detail") or body.get("message"))[:300]
    return str(body)[:300]


def _job_errors(status: dict[str, Any]) -> str:
    details = []
    for document in status.get("documents") or []:
        if isinstance(document, dict) and (document.get("error") or document.get("error_message")):
            details.append(str(document.get("error") or document.get("error_message")))
    if status.get("error"):
        details.append(str(status["error"]))
    return "; ".join(details)[:300] or "no error detail"
