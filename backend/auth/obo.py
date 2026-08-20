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

# MSAL error codes that mean "the user's session is gone, they must sign
# in again" as opposed to a transient/config problem. See:
# https://learn.microsoft.com/entra/identity-platform/reference-error-codes
_REAUTH_REQUIRED_ERROR_CODES = {
    "invalid_grant",  # inbound user assertion (frontend token) has expired
    "interaction_required",
}


class OBOTokenExpiredError(Exception):
    """Raised when the On-Behalf-Of exchange fails because the user's
    session has expired and they need to sign in again — as opposed to a
    configuration or transient error, which should surface as a 5xx."""


class OBOExchangeError(Exception):
    """Raised for any other OBO failure (bad app registration, missing
    consent, transient Entra ID error, etc.)."""


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

    cached = _obo_cache.get(user.oid)
    if cached and cached[1] > time.time() + 30:
        return cached[0]

    app = _msal_app()
    result = app.acquire_token_on_behalf_of(
        user_assertion=user.raw_token,
        scopes=[settings.GRAPH_SCOPE],
    )

    if "access_token" not in result:
        error_code = result.get("error", "")
        error_description = result.get("error_description", "")
        # MSAL also nests the underlying AAD error code inside
        # error_description for OBO failures (e.g. "AADSTS700082: ...").
        # Treat either surface as a re-auth signal.
        if error_code in _REAUTH_REQUIRED_ERROR_CODES or "AADSTS700082" in error_description:
            _obo_cache.pop(user.oid, None)
            raise OBOTokenExpiredError(
                "Your session has expired. Please sign in again."
            )
        raise OBOExchangeError(f"OBO token exchange failed: {error_code}: {error_description}")

    expires_at = time.time() + result.get("expires_in", 3600)
    _obo_cache[user.oid] = (result["access_token"], expires_at)
    return result["access_token"]
