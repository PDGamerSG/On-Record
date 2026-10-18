from fastapi import FastAPI
from fastapi.testclient import TestClient

from wsw_brain.brain.agent_api import create_router
from wsw_brain.contracts import AskResult


class StubAgent:
    def __init__(self):
        self.calls = []

    async def ask(self, question, *, session_id="default", meeting_id=None, k=8):
        self.calls.append((question, session_id, meeting_id, k))
        return AskResult(
            answer="The launch is Friday [u:m1:u00001]",
            citations=[{"utterance_id": "m1:u00001", "text": "Friday"}],
            actions=[],
            tool_trace=[{"tool": "search_meetings", "result_count": 1}],
            cypher=[],
            model="test-model",
            provider="fake",
            session_id=session_id,
        )


def test_agent_router_returns_grounded_answer_contract():
    agent = StubAgent()
    app = FastAPI()
    app.include_router(create_router(agent))

    response = TestClient(app).post(
        "/api/agent/ask",
        json={"question": "When is the launch?", "session_id": "s1", "meeting_id": "m1", "k": 4},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "The launch is Friday [u:m1:u00001]"
    assert response.json()["session_id"] == "s1"
    assert agent.calls == [("When is the launch?", "s1", "m1", 4)]


def test_agent_router_rejects_blank_questions():
    app = FastAPI()
    app.include_router(create_router(StubAgent()))

    response = TestClient(app).post("/api/agent/ask", json={"question": ""})

    assert response.status_code == 422
