"""Document ingestion, storage, search and answers against a disposable local graph; Sarvam is faked."""

import io
import os
import uuid

import pytest
from pypdf import PdfWriter

from wsw_brain.brain import HashEmbedder
from wsw_brain.contracts import LLMResult
from wsw_brain.documents import DocumentIngestor, DocumentRetriever, DocumentStore, answer_question
from wsw_brain.documents.sarvam import DigitisedPart
from wsw_brain.documents.split import DocumentError, Page
from wsw_brain.graph import GraphStore

TEXT = {
    1: "# Vendor agreement\n\nThis agreement is between Acme and Orbit.",
    4: "## Payment terms\n\nInvoices are paid within 45 days of receipt.",
    12: "## Termination\n\nEither party may terminate with 60 days written notice.",
}


def make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class FakeDigitiser:
    """Returns part-relative page numbers, as Document AI does, with text keyed by source page."""

    def __init__(self):
        self.calls = []

    async def digitise(self, filename, data, content_type, language="en-IN"):
        self.calls.append((filename, language))
        first = 1 if "part" not in filename else int(filename.split("-p")[1].split("-")[0])
        last = 12 if "part" not in filename else int(filename.split("-")[-1].split(".")[0])
        pages = [Page(n - first + 1, TEXT.get(n, f"Page {n} filler text.")) for n in range(first, last + 1)]
        return DigitisedPart(job_id=f"job-{first}", status="completed", pages=pages)


class EchoLLM:
    provider = "sarvam"
    model = "gemma4"
    supports_audio = False

    def __init__(self):
        self.prompts = []

    async def chat(self, messages, **kwargs):
        prompt = messages[-1]["content"]
        self.prompts.append(prompt)
        if prompt.startswith("Document:"):
            return LLMResult("A vendor agreement.\n- Pay within 45 days", [], self.model, self.provider, 1.0)
        cited = prompt.split("[d:")[1].split("]")[0]
        return LLMResult(f"Invoices are paid within 45 days [d:{cited}] [d:invented:c9999].", [], self.model,
                         self.provider, 1.0)


@pytest.fixture
def docs():
    graph = GraphStore(os.environ.get("WSW_FALKORDB_URL", "falkor://127.0.0.1:6379"),
                       "on_record_documents_test_" + uuid.uuid4().hex)
    try:
        yield DocumentStore(graph)
    finally:
        graph.reset()
        graph.close()


@pytest.mark.asyncio
async def test_ingest_splits_digitises_and_stores_with_source_page_numbers(docs):
    digitiser, llm, embedder = FakeDigitiser(), EchoLLM(), HashEmbedder(64)
    ingestor = DocumentIngestor(docs, embedder, digitiser, llm=llm, max_pages=5, concurrency=2)
    events = []

    result = await ingestor.ingest("vendor.pdf", make_pdf(12), title="Vendor agreement", language="hi-IN",
                                   on_progress=events.append)

    assert [(p["first_page"], p["last_page"]) for p in result["parts"]] == [(1, 5), (6, 10), (11, 12)]
    assert {lang for _, lang in digitiser.calls} == {"hi-IN"}
    assert [e["stage"] for e in events if e["stage"] != "digitise"] == ["split", "chunk", "embed", "store", "summary"]
    document = docs.get_document(result["doc_id"])
    assert document["pages"] == 12 and document["parts"] == 3 and document["language"] == "hi-IN"
    assert document["summary"].startswith("A vendor agreement")
    termination = [c for c in document["chunks"] if c["heading"] == "Termination"]
    assert termination and termination[0]["page_start"] == 12
    assert docs.list_documents()[0]["chunk_count"] == len(document["chunks"])

    retriever = DocumentRetriever(docs, embedder)
    hits = retriever.retrieve("When are invoices paid?", k=3)
    assert hits[0]["heading"] == "Payment terms" and hits[0]["page_start"] == 4
    assert "utterance_id" not in hits[0]

    answer = await answer_question(llm, retriever, "When are invoices paid?")
    assert "[d:invented:c9999]" not in answer["answer"]
    assert answer["citations"] and answer["citations"][0]["id"] in answer["answer"]
    assert answer["provider"] == "sarvam"

    assert docs.delete_document(result["doc_id"]) is True
    assert docs.get_document(result["doc_id"]) is None
    assert docs.search_fulltext("invoices") == []


@pytest.mark.asyncio
async def test_page_budget_is_enforced_before_calling_sarvam(docs):
    digitiser = FakeDigitiser()
    ingestor = DocumentIngestor(docs, HashEmbedder(64), digitiser, max_total_pages=5)
    with pytest.raises(DocumentError, match="12 pages; the limit is 5"):
        await ingestor.ingest("big.pdf", make_pdf(12))
    assert digitiser.calls == []


@pytest.mark.asyncio
async def test_answer_without_matches_skips_the_model(docs):
    docs.ensure_schema(64)
    llm = EchoLLM()
    answer = await answer_question(llm, DocumentRetriever(docs, HashEmbedder(64)), "anything at all?")
    assert answer["citations"] == [] and llm.prompts == []


class CrossSourceLLM:
    provider = "sarvam"
    model = "gemma4"
    supports_audio = False

    def __init__(self):
        self.messages = []

    async def chat(self, messages, **kwargs):
        self.messages = messages
        prompt = messages[-1]["content"]
        doc = prompt.split("[d:")[1].split("]")[0]
        line = prompt.split("[u:")[1].split("]")[0]
        return LLMResult(f"The agreement says 45 days [d:{doc}], but Priya moved it to 30 days [u:{line}] "
                         "[u:m9:u99999].", [], self.model, self.provider, 1.0)


@pytest.mark.asyncio
async def test_answers_can_combine_meetings_and_documents(docs):
    from wsw_brain.brain import Retriever
    from wsw_brain.contracts import Utterance

    embedder = HashEmbedder(64)
    docs.graph.ensure_schema(embedder.dim)
    ingestor = DocumentIngestor(docs, embedder, FakeDigitiser(), max_pages=10)
    await ingestor.ingest("vendor.pdf", make_pdf(12), title="Vendor agreement", summarise=False)
    docs.graph.create_meeting("m-pay", "Payments review", "mic", 1792062000000)
    lines = [Utterance("m-pay", 0, "S1", 0.0, 4.0, "Invoices will now be paid within 30 days, not 45.")]
    docs.graph.write_utterances(lines, embedder.embed_documents([u.text for u in lines]))
    docs.graph.name_speaker("m-pay", "S1", "Priya")
    llm = CrossSourceLLM()

    answer = await answer_question(llm, DocumentRetriever(docs, embedder), "When are invoices paid?",
                                   meetings=Retriever(docs.graph, embedder))

    assert "Meeting lines:" in llm.messages[-1]["content"]
    assert 'Meeting "Payments review"' in llm.messages[-1]["content"]
    assert "disagree" in llm.messages[0]["content"]
    assert [c["meeting_id"] for c in answer["meeting_citations"]] == ["m-pay"]
    assert answer["meeting_citations"][0]["meeting_date"]
    assert "[u:m9:u99999]" not in answer["answer"] and answer["citations"]
