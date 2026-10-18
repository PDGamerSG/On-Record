import pytest

from wsw_brain.brain.agent import MeetingAgent
from wsw_brain.contracts import LLMResult


class StubRetriever:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def retrieve(self, question, meeting_id=None, k=8):
        self.calls.append((question, meeting_id, k))
        return self.hits, ["MATCH (u:Utterance) RETURN u"]


class StubLLM:
    model = "test-model"
    provider = "fake"

    def __init__(self, text):
        self.text = text
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return LLMResult(
            text=self.text,
            tool_calls=[],
            model=self.model,
            provider=self.provider,
            latency_ms=3.0,
        )


@pytest.mark.asyncio
async def test_agent_retrieves_context_and_keeps_only_grounded_citations():
    hits = [
        {
            "utterance_id": "meeting-1:u00001",
            "speaker": "S1",
            "text": "The launch is Friday.",
            "t_start": 12.0,
        }
    ]
    retriever = StubRetriever(hits)
    llm = StubLLM("The launch is Friday [u:meeting-1:u00001] [u:missing]")
    agent = MeetingAgent(llm, retriever)

    result = await agent.ask("When is the launch?", session_id="session-1", meeting_id="meeting-1", k=4)

    assert result.answer == "The launch is Friday [u:meeting-1:u00001]"
    assert result.citations == hits
    assert result.cypher == ["MATCH (u:Utterance) RETURN u"]
    assert result.tool_trace[0]["tool"] == "search_meetings"
    assert result.tool_trace[0]["args"] == {"meeting_id": "meeting-1", "query": "When is the launch?", "k": 4}
    assert result.tool_trace[0]["result_count"] == 1
    assert "ms" in result.tool_trace[0]
    assert retriever.calls == [("When is the launch?", "meeting-1", 4)]
    assert "[u:meeting-1:u00001]" in llm.calls[0][-1]["content"]
    assert "When is the launch?" in llm.calls[0][-1]["content"]


@pytest.mark.asyncio
async def test_agent_keeps_recent_history_per_session():
    retriever = StubRetriever([{"utterance_id": "u1", "speaker": "S1", "text": "Friday"}])
    llm = StubLLM("Friday [u:u1]")
    agent = MeetingAgent(llm, retriever)

    await agent.ask("When?", session_id="same")
    await agent.ask("And who said that?", session_id="same")

    second_messages = llm.calls[1]
    assert [message["role"] for message in second_messages] == ["system", "user", "assistant", "user"]
    assert second_messages[1]["content"] == "When?"


@pytest.mark.asyncio
async def test_agent_returns_grounded_fallback_without_calling_model():
    retriever = StubRetriever([])
    llm = StubLLM("should not be used")
    agent = MeetingAgent(llm, retriever)

    result = await agent.ask("What was decided?")

    assert result.answer == "I couldn't find supporting evidence in the meeting record."
    assert result.citations == []
    assert result.tool_trace[0]["result_count"] == 0
    assert llm.calls == []


@pytest.mark.asyncio
async def test_agent_rejects_blank_questions():
    agent = MeetingAgent(StubLLM("unused"), StubRetriever([]))

    with pytest.raises(ValueError, match="question must not be blank"):
        await agent.ask("  ")


class SequenceLLM:
    """Replies with each text in turn (the last one repeats) and records every call's messages and options."""

    model = "test-model"
    provider = "fake"

    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = []
        self.options = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        self.options.append(kwargs)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return LLMResult(text=text, tool_calls=[], model=self.model, provider=self.provider, latency_ms=1.0)


PRICE_HITS = [
    {"utterance_id": "m1:u00001", "speaker": "S1", "text": "The starter plan costs 4,999 rupees a month.", "t_start": 3.0}
]
FALLBACK = "I couldn't find supporting evidence in the meeting record."


def _check_entry(result):
    entry = result.tool_trace[-1]
    assert entry["tool"] == "check_answer" and "ms" in entry
    return entry


@pytest.mark.asyncio
async def test_agent_asks_again_when_a_number_is_not_in_the_cited_evidence():
    llm = SequenceLLM("Starter costs Rs. 5,999 a month [u:m1:u00001].", "Starter costs Rs. 4,999 a month [u:m1:u00001].")
    agent = MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="enforce")

    result = await agent.ask("What does the starter plan cost?")

    assert result.answer == "Starter costs Rs. 4,999 a month [u:m1:u00001]."
    assert result.citations == PRICE_HITS
    assert len(llm.calls) == 2 and llm.options[1]["temperature"] == 0
    assert llm.calls[1][-2] == {"role": "assistant", "content": "Starter costs Rs. 5,999 a month [u:m1:u00001]."}
    assert "5999" in llm.calls[1][-1]["content"]
    entry = _check_entry(result)
    assert entry["args"]["retried"] is True and entry["result_count"] == 0


@pytest.mark.asyncio
async def test_agent_drops_a_wrong_number_the_model_repeats():
    llm = SequenceLLM("Starter costs Rs. 5,999 a month [u:m1:u00001].")
    agent = MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="enforce")

    result = await agent.ask("What does the starter plan cost?")

    assert result.answer == FALLBACK and result.citations == []
    entry = _check_entry(result)
    assert entry["result_count"] == 1 and entry["args"]["unsupported_numbers"] == ["5999"]


@pytest.mark.asyncio
async def test_agent_withholds_an_uncited_claim_the_evidence_does_not_support():
    llm = SequenceLLM("Starter costs Rs. 4,999 a month [u:m1:u00001]. Marketing doubled its festive budget.")
    agent = MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="enforce")

    result = await agent.ask("What does the starter plan cost?")

    assert result.answer == "Starter costs Rs. 4,999 a month [u:m1:u00001]."
    assert len(llm.calls) == 1
    assert _check_entry(result)["args"]["withheld"] == ["Marketing doubled its festive budget."]


@pytest.mark.asyncio
async def test_report_mode_keeps_the_answer_and_traces_what_would_be_removed():
    llm = SequenceLLM("Starter costs Rs. 5,999 a month [u:m1:u00001].")
    agent = MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="report")

    result = await agent.ask("What does the starter plan cost?")

    assert result.answer == "Starter costs Rs. 5,999 a month [u:m1:u00001]." and len(llm.calls) == 1
    entry = _check_entry(result)
    assert entry["args"]["mode"] == "report" and entry["args"]["retried"] is False and entry["result_count"] == 1


@pytest.mark.asyncio
async def test_answer_checks_can_be_turned_off():
    llm = SequenceLLM("Starter costs Rs. 5,999 a month [u:m1:u00001].")
    agent = MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="off")

    result = await agent.ask("What does the starter plan cost?")

    assert result.answer == "Starter costs Rs. 5,999 a month [u:m1:u00001]."
    assert [entry["tool"] for entry in result.tool_trace] == ["search_meetings"]
    with pytest.raises(ValueError, match="answer_checks"):
        MeetingAgent(llm, StubRetriever(PRICE_HITS), answer_checks="strict")
