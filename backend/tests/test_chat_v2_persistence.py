"""Verifies backend/api/chat_v2.py's conversation persistence and
multi-turn history wiring: a conversation is created lazily on first send,
both turns get persisted, and a follow-up call sharing that conversation_id
receives the prior turn as history — the LangGraphRAGService pipeline
itself is mocked out here (see test_langgraph_pipeline.py for that)."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.api import chat_v2
from backend.main import app
from backend.models.chat import ChatResponse
from backend.services.storage import get_conversation_store
from backend.services.storage.sqlite_store import SqliteConversationStore


def _make_token(oid: str) -> str:
    payload = {
        "oid": oid,
        "preferred_username": f"{oid}@contoso.com",
        "name": "Test User",
        "tid": "test-tenant",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, "unused-secret", algorithm="HS256")


@pytest.fixture
def client(tmp_path):
    store = SqliteConversationStore(tmp_path / "test.db")
    app.dependency_overrides[get_conversation_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.pop(get_conversation_store, None)


def _auth(oid: str) -> dict:
    return {"Authorization": f"Bearer {_make_token(oid)}"}


def test_first_message_creates_conversation_and_persists_both_turns(client, monkeypatch):
    async def fake_answer_question(user, question, history=None):
        assert history == []  # brand-new conversation, nothing to load yet
        return ChatResponse(answer="Here's the answer.", citations=[], retrieval_attempts=1)

    monkeypatch.setattr(chat_v2.rag_service_v2, "answer_question", fake_answer_question)

    res = client.post("/api/chat/v2", json={"question": "first question"}, headers=_auth("user-a"))
    assert res.status_code == 200
    body = res.json()
    assert body["conversation_id"]
    assert body["answer"] == "Here's the answer."

    detail = client.get(f"/api/conversations/{body['conversation_id']}", headers=_auth("user-a")).json()
    contents = [(m["role"], m["content"]) for m in detail["messages"]]
    assert contents == [("user", "first question"), ("assistant", "Here's the answer.")]


def test_followup_message_receives_prior_turn_as_history(client, monkeypatch):
    captured_history = []

    async def fake_answer_question(user, question, history=None):
        captured_history.append(history)
        return ChatResponse(answer=f"answer to: {question}", citations=[], retrieval_attempts=1)

    monkeypatch.setattr(chat_v2.rag_service_v2, "answer_question", fake_answer_question)

    first = client.post("/api/chat/v2", json={"question": "what is X?"}, headers=_auth("user-a"))
    conversation_id = first.json()["conversation_id"]

    second = client.post(
        "/api/chat/v2",
        json={"question": "and what about Y?", "conversation_id": conversation_id},
        headers=_auth("user-a"),
    )
    assert second.status_code == 200

    # First call saw no history; the second saw the first exchange.
    assert captured_history[0] == []
    assert len(captured_history[1]) == 2
    assert captured_history[1][0].role == "user"
    assert captured_history[1][0].content == "what is X?"
    assert captured_history[1][1].role == "assistant"
    assert captured_history[1][1].content == "answer to: what is X?"


def test_unknown_conversation_id_is_404(client, monkeypatch):
    async def fake_answer_question(user, question, history=None):
        raise AssertionError("should not reach the pipeline for an unowned conversation")

    monkeypatch.setattr(chat_v2.rag_service_v2, "answer_question", fake_answer_question)

    res = client.post(
        "/api/chat/v2",
        json={"question": "hi", "conversation_id": "does-not-exist"},
        headers=_auth("user-a"),
    )
    assert res.status_code == 404
