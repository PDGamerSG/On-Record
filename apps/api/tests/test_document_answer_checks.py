"""Answer checks on document answers, with stub retrievers and a scripted model (no graph needed)."""

from __future__ import annotations

import pytest

from wsw_brain.contracts import LLMResult
from wsw_brain.documents.answer import answer_question

PASSAGE = {
    "id": "doc-policy-1:c0001",
    "doc_title": "Vendor policy",
    "page_start": 2,
    "page_end": 2,
    "heading": "Payments",
    "text": "Invoices are paid within 45 days of receipt.",
}
MEETING_LINE = {
    "utterance_id": "m1:u00004",
    "speaker": "S1",
    "speaker_name": "Priya",
    "meeting_title": "Finance sync",
    "t_start": 30.0,
    "text": "From November we pay invoices within 30 days.",
}
NO_ANSWER = "The uploaded documents do not mention that."


class StubDocuments:
    docs = None

    def retrieve(self, question, k, doc_id):
        return [dict(PASSAGE)]


class StubMeetings:
    def retrieve(self, query, k=8):
        return [dict(MEETING_LINE)], []


class SequenceLLM:
    """Replies with each text in turn (the last one repeats) and records every call."""

    model = "gemma4"
    provider = "sarvam"

    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []
        self.options = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        self.options.append(kwargs)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return LLMResult(text=text, tool_calls=[], model=self.model, provider=self.provider, latency_ms=1.0)


@pytest.mark.asyncio
async def test_document_answer_with_a_made_up_number_is_asked_again():
    llm = SequenceLLM(
        "Invoices are paid within 60 days [d:doc-policy-1:c0001].",
        "Invoices are paid within 45 days [d:doc-policy-1:c0001].",
    )
    result = await answer_question(llm, StubDocuments(), "When are invoices paid?", answer_checks="enforce")

    assert result["answer"] == "Invoices are paid within 45 days [d:doc-policy-1:c0001]."
    assert result["citations"] == [PASSAGE]
    assert len(llm.calls) == 2 and llm.options[1]["temperature"] == 0 and "60" in llm.calls[1][-1]["content"]
    assert result["checks"] == {"mode": "enforce", "retried": True, "withheld": 0, "withheld_sentences": [],
                                "unsupported_numbers": []}  # fmt: skip


@pytest.mark.asyncio
async def test_document_answer_that_repeats_a_wrong_number_falls_back():
    llm = SequenceLLM("Invoices are paid within 60 days [d:doc-policy-1:c0001].")
    result = await answer_question(llm, StubDocuments(), "When are invoices paid?", answer_checks="enforce")

    assert result["answer"] == NO_ANSWER and result["citations"] == []
    assert result["checks"]["withheld"] == 1 and result["checks"]["unsupported_numbers"] == ["60"]


@pytest.mark.asyncio
async def test_meeting_lines_count_as_evidence_for_document_answers():
    llm = SequenceLLM(
        "The policy says 45 days [d:doc-policy-1:c0001]. Priya said invoices are paid within 30 days from "
        "November [u:m1:u00004]."
    )
    result = await answer_question(
        llm, StubDocuments(), "When are invoices paid?", meetings=StubMeetings(), answer_checks="enforce"
    )

    assert result["answer"] == llm.texts[0] and len(llm.calls) == 1
    assert result["citations"] == [PASSAGE]
    assert [hit["utterance_id"] for hit in result["meeting_citations"]] == ["m1:u00004"]
    assert result["checks"]["withheld"] == 0 and result["checks"]["retried"] is False


@pytest.mark.asyncio
async def test_report_mode_returns_the_document_answer_unchanged():
    llm = SequenceLLM("Invoices are paid within 60 days [d:doc-policy-1:c0001].")
    result = await answer_question(llm, StubDocuments(), "When are invoices paid?", answer_checks="report")

    assert (
        result["answer"] == "Invoices are paid within 60 days [d:doc-policy-1:c0001]." and len(llm.calls) == 1
    )
    assert result["checks"]["mode"] == "report" and result["checks"]["withheld"] == 1


@pytest.mark.asyncio
async def test_off_mode_skips_document_answer_checks():
    llm = SequenceLLM("Invoices are paid within 60 days [d:doc-policy-1:c0001].")
    result = await answer_question(llm, StubDocuments(), "When are invoices paid?", answer_checks="off")

    assert (
        result["answer"] == "Invoices are paid within 60 days [d:doc-policy-1:c0001]."
        and "checks" not in result
    )
    with pytest.raises(ValueError, match="answer_checks"):
        await answer_question(llm, StubDocuments(), "When are invoices paid?", answer_checks="strict")
