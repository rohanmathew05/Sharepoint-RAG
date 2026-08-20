"""Verifies mid-session token/OBO expiry surfaces as a clean 401 (with a
re-auth signal the frontend acts on) instead of an unhandled 500."""
import jwt
import pytest
from fastapi.testclient import TestClient

from backend.auth import obo as obo_module
from backend.core.config import get_settings
from backend.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def real_mode(monkeypatch):
    """These tests exercise the non-demo auth path."""
    settings = get_settings()
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    monkeypatch.setattr(settings, "ENTRA_TENANT_ID", "test-tenant")
    monkeypatch.setattr(settings, "ENTRA_CLIENT_ID", "test-client")
    obo_module._obo_cache.clear()
    yield
    obo_module._obo_cache.clear()


def _make_token(exp_offset_seconds: int) -> str:
    import time

    payload = {
        "oid": "user-oid-123",
        "preferred_username": "user@contoso.com",
        "name": "Test User",
        "tid": "test-tenant",
        "exp": int(time.time()) + exp_offset_seconds,
    }
    return jwt.encode(payload, "unused-secret", algorithm="HS256")


def test_expired_frontend_token_gets_clean_401():
    expired_token = _make_token(exp_offset_seconds=-3600)
    res = client.post(
        "/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == 401
    assert "expired" in res.json()["detail"].lower()


def test_obo_exchange_failure_maps_to_401_not_500(monkeypatch):
    valid_token = _make_token(exp_offset_seconds=3600)

    async def fake_get_graph_token(user):
        raise obo_module.OBOTokenExpiredError("Your session has expired. Please sign in again.")

    monkeypatch.setattr(obo_module, "get_graph_token_on_behalf_of", fake_get_graph_token)
    # SharePointService imports the function directly, so patch it there too.
    import backend.services.sharepoint as sharepoint_module

    monkeypatch.setattr(sharepoint_module, "get_graph_token_on_behalf_of", fake_get_graph_token)

    res = client.post(
        "/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert res.status_code == 401
    assert res.json()["error_code"] == "obo_token_expired"
    assert res.headers["www-authenticate"] == "Bearer"


def test_other_obo_failures_map_to_502_not_500(monkeypatch):
    valid_token = _make_token(exp_offset_seconds=3600)

    async def fake_get_graph_token(user):
        raise obo_module.OBOExchangeError("OBO token exchange failed: invalid_client: bad secret")

    import backend.services.sharepoint as sharepoint_module

    monkeypatch.setattr(sharepoint_module, "get_graph_token_on_behalf_of", fake_get_graph_token)

    res = client.post(
        "/api/chat",
        json={"question": "test"},
        headers={"Authorization": f"Bearer {valid_token}"},
    )
    assert res.status_code == 502
    assert res.json()["error_code"] == "obo_exchange_failed"
