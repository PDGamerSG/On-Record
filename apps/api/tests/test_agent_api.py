from fastapi import FastAPI
from fastapi.testclient import TestClient

from wsw_brain.app import create_app
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


def test_agent_router_exposes_web_compatibility_alias() -> None:
    agent = StubAgent()
    app = FastAPI()
    app.include_router(create_router(agent))

    response = TestClient(app).post("/api/ask", json={"question": "When is the launch?"})

    assert response.status_code == 200
    assert response.json()["answer"] == "The launch is Friday [u:m1:u00001]"
    assert agent.calls == [("When is the launch?", "default", None, 8)]


def test_agent_router_rejects_blank_questions():
    app = FastAPI()
    app.include_router(create_router(StubAgent()))

    response = TestClient(app).post("/api/agent/ask", json={"question": ""})

    assert response.status_code == 422


def test_agent_router_publishes_response_schema():
    client = TestClient(FastAPI())
    client.app.include_router(create_router(StubAgent()))

    schema = client.get("/openapi.json").json()
    response_schema = schema["paths"]["/api/agent/ask"]["post"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert response_schema == {"$ref": "#/components/schemas/AskResponse"}
    assert set(schema["components"]["schemas"]["AskResponse"]["properties"]) == {
        "answer",
        "citations",
        "actions",
        "tool_trace",
        "cypher",
        "model",
        "provider",
        "session_id",
        "timings",
        "transcript",
        "transcript_provider",
    }


def test_main_app_mounts_agent_router_when_an_agent_is_injected():
    agent = StubAgent()

    client = TestClient(create_app(meeting_agent=agent))
    response = client.post("/api/agent/ask", json={"question": "When is the launch?"})

    assert response.status_code == 200
    assert agent.calls == [("When is the launch?", "default", None, 8)]
    assert client.get("/api/capabilities").json()["features"] == [
        "status",
        "documents",
        "events",
        "agent",
    ]
