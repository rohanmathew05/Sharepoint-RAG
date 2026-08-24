"""Verifies backend/api/conversations.py against a real FastAPI TestClient,
with the storage dependency overridden to a tmp_path-backed SQLite store —
this is the actual payoff of the ConversationStore abstraction: tests swap
storage via a plain FastAPI dependency override, no mocking of SQL calls."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

from backend.main import app
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


def test_create_list_and_get_conversation(client):
    create_res = client.post("/api/conversations", headers=_auth("user-a"))
    assert create_res.status_code == 201
    conversation_id = create_res.json()["id"]

    list_res = client.get("/api/conversations", headers=_auth("user-a"))
    assert list_res.status_code == 200
    assert [c["id"] for c in list_res.json()] == [conversation_id]

    get_res = client.get(f"/api/conversations/{conversation_id}", headers=_auth("user-a"))
    assert get_res.status_code == 200
    assert get_res.json()["messages"] == []


def test_get_nonexistent_conversation_is_404(client):
    res = client.get("/api/conversations/does-not-exist", headers=_auth("user-a"))
    assert res.status_code == 404


def test_rename_conversation(client):
    conversation_id = client.post("/api/conversations", headers=_auth("user-a")).json()["id"]

    res = client.patch(
        f"/api/conversations/{conversation_id}",
        json={"title": "Renamed"},
        headers=_auth("user-a"),
    )
    assert res.status_code == 200
    assert res.json()["title"] == "Renamed"


def test_delete_conversation(client):
    conversation_id = client.post("/api/conversations", headers=_auth("user-a")).json()["id"]

    res = client.delete(f"/api/conversations/{conversation_id}", headers=_auth("user-a"))
    assert res.status_code == 204

    get_res = client.get(f"/api/conversations/{conversation_id}", headers=_auth("user-a"))
    assert get_res.status_code == 404


def test_one_user_cannot_see_or_modify_another_users_conversation(client):
    conversation_id = client.post("/api/conversations", headers=_auth("user-a")).json()["id"]

    assert client.get("/api/conversations", headers=_auth("user-b")).json() == []
    assert client.get(f"/api/conversations/{conversation_id}", headers=_auth("user-b")).status_code == 404
    assert (
        client.patch(
            f"/api/conversations/{conversation_id}",
            json={"title": "hijacked"},
            headers=_auth("user-b"),
        ).status_code
        == 404
    )
    assert client.delete(f"/api/conversations/{conversation_id}", headers=_auth("user-b")).status_code == 404

    # Still there from user-a's perspective, untouched.
    still_there = client.get(f"/api/conversations/{conversation_id}", headers=_auth("user-a"))
    assert still_there.status_code == 200
    assert still_there.json()["title"] != "hijacked"
