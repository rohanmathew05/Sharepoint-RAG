"""Microsoft OAuth 2.0 On-Behalf-Of (OBO) token exchange.

The FastAPI backend never uses its own application identity to call
Microsoft Graph for search or content retrieval. Instead it exchanges the
user's inbound access token for a *delegated* Graph token scoped to that
same user, via MSAL's `acquire_token_on_behalf_of`. Every Graph call made
with the resulting token is therefore subject to that user's actual
SharePoint permissions — Graph itself is the enforcement point, not this
service.
"""
import time

import msal

from backend.core.config import get_settings
from backend.models.auth import UserContext

_obo_cache: dict[str, tuple[str, float]] = {}


def _msal_app() -> msal.ConfidentialClientApplication:
    settings = get_settings()
    authority = f"https://login.microsoftonline.com/{settings.ENTRA_TENANT_ID}"
    return msal.ConfidentialClientApplication(
        client_id=settings.ENTRA_CLIENT_ID,
        client_credential=settings.ENTRA_CLIENT_SECRET,
        authority=authority,
    )


async def get_graph_token_on_behalf_of(user: UserContext) -> str:
    """Exchange the user's inbound token for a delegated Graph token.

    Cached per-user for the lifetime of the token to avoid an OBO round
    trip on every request.
    """
    settings = get_settings()

    if settings.DEMO_MODE:
        # No real Entra ID tenant in the demo — the "delegated token" is a
        # stand-in that SharePointService/GraphService use purely to look
        # up which fixture user's document set to search.
        return f"demo-graph-token::{user.oid}"

    cached = _obo_cache.get(user.oid)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    app = _msal_app()
    result = app.acquire_token_on_behalf_of(
        user_assertion=user.raw_token,
        scopes=[settings.GRAPH_SCOPE],
    )

    if "access_token" not in result:
        raise RuntimeError(
            "OBO token exchange failed: "
            f"{result.get('error')}: {result.get('error_description')}"
        )

    expires_at = time.time() + result.get("expires_in", 3600)
    _obo_cache[user.oid] = (result["access_token"], expires_at)
    return result["access_token"]
