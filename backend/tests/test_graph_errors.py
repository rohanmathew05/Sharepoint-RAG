"""Verifies a non-2xx response from Microsoft Graph itself (rate limiting,
transient errors) surfaces as a typed 429/502 instead of an unhandled 500
(previously graph.py's resp.raise_for_status() propagated unhandled)."""
import jwt
from fastapi.testclient import TestClient

from backend.main import app
from backend.services.graph import GraphAPIError

client = TestClient(app)


def _valid_token() -> str:
    import time

    payload = {
        "oid": "user-oid-123",
        "preferred_username": "user@contoso.com",
        "name": "Test User",
        "tid": "test-tenant",
        "exp": int(time.time()) + 3600,
    }
    return jwt.encode(payload, "unused-secret", algorithm="HS256")


def test_graph_rate_limit_maps_to_429_with_retry_after(monkeypatch):
    async def fake_get_graph_token(user):
        return "fake-graph-token"

    async def fake_search_sharepoint(self, query, size=8):
        raise GraphAPIError("rate limited", status_code=429, retry_after="30")

    import backend.services.sharepoint as sharepoint_module
    from backend.services.graph import GraphService

    monkeypatch.setattr(sharepoint_module, "get_graph_token_on_behalf_of", fake_get_graph_token)
    monkeypatch.setattr(GraphService, "search_sharepoint", fake_search_sharepoint)

    res = client.post(
        "/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {_valid_token()}"},
    )
    assert res.status_code == 429
    assert res.json()["error_code"] == "graph_rate_limited"
    assert res.headers["retry-after"] == "30"


def test_other_graph_errors_map_to_502_not_500(monkeypatch):
    async def fake_get_graph_token(user):
        return "fake-graph-token"

    async def fake_search_sharepoint(self, query, size=8):
        raise GraphAPIError("boom", status_code=503)

    import backend.services.sharepoint as sharepoint_module
    from backend.services.graph import GraphService

    monkeypatch.setattr(sharepoint_module, "get_graph_token_on_behalf_of", fake_get_graph_token)
    monkeypatch.setattr(GraphService, "search_sharepoint", fake_search_sharepoint)

    res = client.post(
        "/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {_valid_token()}"},
    )
    assert res.status_code == 502
    assert res.json()["error_code"] == "graph_error"
