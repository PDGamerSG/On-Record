"""Document HTTP routes with Sarvam, the model and the graph replaced by in-process fakes."""

import asyncio
import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from wsw_brain.routes import documents as routes


def make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class FakeIngestor:
    def plan(self, filename, data):
        return routes.split_document(filename, data, 10)

    async def ingest(self, filename, data, *, title=None, doc_id=None, language=None, on_progress=None):
        on_progress({"stage": "split", "parts": 2, "pages": 12})
        await asyncio.sleep(0)
        return {"doc_id": doc_id, "title": title, "pages": 12, "chunks": 3, "parts": []}


class FakeSpeech:
    async def translate(self, text, target, source="auto"):
        return f"[{target}] {text}"

    async def speak(self, text, language, speaker="priya", pace=1.0):
        return b"RIFF....WAVE"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(routes, "_ingestor", lambda: FakeIngestor())
    monkeypatch.setattr(routes, "_speech", lambda: FakeSpeech())

    async def fake_answer(llm, retriever, question, *, doc_id=None, k=6, meetings=None):
        return {"answer": f"Answer to {question} [d:doc:c0001]", "citations": [], "hits": [], "model": "gemma4",
                "provider": "sarvam", "timings": {"retrieval_ms": 1.0}}

    monkeypatch.setattr(routes, "answer_question", fake_answer)
    monkeypatch.setattr(routes, "get_llm", lambda: None)
    monkeypatch.setattr(routes, "get_embedder", lambda: None)
    monkeypatch.setattr(routes, "_docs", lambda: None)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as test_client:
        yield test_client


def test_split_preview_reports_parts(client):
    response = client.post("/api/documents/split", files={"file": ("big.pdf", make_pdf(12), "application/pdf")})
    assert response.status_code == 200
    body = response.json()
    assert body["pages"] == 12 and body["kind"] == "pdf"
    assert [(p["first_page"], p["last_page"]) for p in body["parts"]] == [(1, 10), (11, 12)]


def test_split_rejects_non_documents(client):
    response = client.post("/api/documents/split", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400 and "unsupported file type" in response.json()["detail"]


def test_upload_runs_a_background_job(client):
    response = client.post("/api/documents", files={"file": ("big.pdf", make_pdf(12), "application/pdf")},
                           data={"title": "Big"})
    assert response.status_code == 200
    job = response.json()["job"]
    assert response.json()["parts"] == 2
    for _ in range(50):
        state = client.get(f"/api/documents/jobs/{job['id']}").json()
        if state["status"] != "running":
            break
    assert state["status"] == "done" and state["result"]["title"] == "Big"
    assert state["events"][0]["stage"] == "split"
    assert client.get("/api/documents/jobs/missing").status_code == 404


def test_jobs_endpoint_lists_uploaded_jobs(client):
    response = client.post("/api/documents", files={"file": ("queued.pdf", make_pdf(1), "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job"]["id"]

    listing = client.get("/api/documents/jobs")

    assert listing.status_code == 200
    assert any(job["id"] == job_id and job["filename"] == "queued.pdf" for job in listing.json())


def test_jobs_endpoint_filters_by_status(client):
    response = client.post("/api/documents", files={"file": ("filtered.pdf", make_pdf(1), "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job"]["id"]
    for _ in range(50):
        state = client.get(f"/api/documents/jobs/{job_id}").json()
        if state["status"] != "running":
            break
    assert state["status"] == "done"

    listing = client.get("/api/documents/jobs", params={"status": "done"})

    assert listing.status_code == 200
    assert all(job["status"] == "done" for job in listing.json())
    assert any(job["id"] == job_id for job in listing.json())
    assert client.get("/api/documents/jobs", params={"status": "waiting"}).status_code == 422


def test_completed_job_can_be_removed_from_the_job_store(client):
    response = client.post("/api/documents", files={"file": ("remove-me.pdf", make_pdf(1), "application/pdf")})
    assert response.status_code == 200
    job_id = response.json()["job"]["id"]
    for _ in range(50):
        state = client.get(f"/api/documents/jobs/{job_id}").json()
        if state["status"] != "running":
            break
    assert state["status"] == "done"

    deleted = client.delete(f"/api/documents/jobs/{job_id}")

    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}
    assert client.get(f"/api/documents/jobs/{job_id}").status_code == 404


def test_jobs_endpoint_limits_the_number_of_results(client):
    client.post("/api/documents", files={"file": ("first.pdf", make_pdf(1), "application/pdf")})
    client.post("/api/documents", files={"file": ("second.pdf", make_pdf(1), "application/pdf")})

    listing = client.get("/api/documents/jobs", params={"limit": 1})

    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert client.get("/api/documents/jobs", params={"limit": 0}).status_code == 422


def test_ask_translates_when_a_language_is_requested(client):
    plain = client.post("/api/documents/ask", json={"question": "When?"}).json()
    assert "translated_answer" not in plain
    translated = client.post("/api/documents/ask", json={"question": "When?", "language": "kn-IN"}).json()
    assert translated["translated_answer"].startswith("[kn-IN] Answer to When?")
    assert translated["answer_language"] == "kn-IN" and "translate_ms" in translated["timings"]
    assert client.post("/api/documents/ask", json={"question": "When?", "language": "kannada"}).status_code == 422


def test_ask_names_the_model_that_translated_the_answer(client):
    mayura = client.post("/api/documents/ask", json={"question": "When?", "language": "kn-IN"}).json()
    assert mayura["translated_by"] == "Sarvam Mayura"
    translate = client.post("/api/documents/ask", json={"question": "When?", "language": "ur-IN"}).json()
    assert translate["translated_answer"].startswith("[ur-IN] Answer to When?")
    assert translate["translated_by"] == "Sarvam Translate"


class FailingSpeech(FakeSpeech):
    async def translate(self, text, target, source="auto"):
        raise routes.SarvamSpeechError("Sarvam could not identify the source language")


class SlowSpeech(FakeSpeech):
    async def translate(self, text, target, source="auto"):
        await asyncio.sleep(5)
        return text


@pytest.mark.parametrize(
    ("speech", "error"),
    [(FailingSpeech, "could not identify"), (SlowSpeech, "longer than 0.05 s")],
)
def test_ask_still_answers_when_translation_fails_or_times_out(client, monkeypatch, speech, error):
    monkeypatch.setattr(routes, "_speech", lambda: speech())
    monkeypatch.setattr(routes, "TRANSLATE_TIMEOUT_S", 0.05)
    response = client.post("/api/documents/ask", json={"question": "When?", "language": "ur-IN"})
    assert response.status_code == 200
    result = response.json()
    assert result["answer"].startswith("Answer to When?") and error in result["translation_error"]
    assert "translated_answer" not in result and "translated_by" not in result
    assert "translate_ms" in result["timings"]


def test_speak_returns_wav(client):
    response = client.post("/api/documents/speak", json={"text": "Hello", "language": "hi-IN"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav" and response.content.startswith(b"RIFF")
