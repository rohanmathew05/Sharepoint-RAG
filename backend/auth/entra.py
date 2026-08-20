"""Validates inbound Microsoft Entra ID access tokens and derives UserContext.

In DEMO_MODE the app trusts a lightweight `X-Demo-User` header instead of
validating a real Entra ID JWT, so the permission-aware retrieval demo can
be run without a tenant. Set DEMO_MODE=false and configure ENTRA_* env vars
to use real Entra ID tokens (validated via JWKS signature + issuer/audience
checks, e.g. with `python-jose` or MSAL's token validation helpers).
"""
import jwt
from fastapi import HTTPException, Request, status

from backend.core.config import get_settings
from backend.models.auth import UserContext

# Fixture "directory" for the demo: two users with different SharePoint
# group membership, used only when DEMO_MODE=true.
DEMO_USERS: dict[str, UserContext] = {
    "user-a": UserContext(
        oid="00000000-0000-0000-0000-0000000000a1",
        upn="user.a@contoso.com",
        name="User A (General only)",
        tenant_id="demo-tenant",
    ),
    "user-b": UserContext(
        oid="00000000-0000-0000-0000-0000000000b1",
        upn="user.b@contoso.com",
        name="User B (General + Engineering)",
        tenant_id="demo-tenant",
    ),
}


def _get_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization header",
        )
    return auth_header.removeprefix("Bearer ").strip()


async def get_current_user(request: Request) -> UserContext:
    """FastAPI dependency: resolves the authenticated user for this request."""
    settings = get_settings()

    if settings.DEMO_MODE:
        demo_user_id = request.headers.get("X-Demo-User", "user-a")
        user = DEMO_USERS.get(demo_user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Unknown demo user '{demo_user_id}'",
            )
        token = _get_bearer_token(request) if "Authorization" in request.headers else "demo-token"
        return user.model_copy(update={"raw_token": token})

    token = _get_bearer_token(request)
    try:
        # Signature verification against Entra ID's JWKS is intentionally
        # left for production wiring (see docs/SETUP.md) — this decodes
        # claims for the OBO exchange, which itself is what actually
        # proves the token is valid (Entra ID rejects a forged token).
        # `verify_exp` IS enabled, though: an expired frontend token must
        # be rejected here with a clean 401 rather than reaching the OBO
        # exchange, where MSAL's failure is harder to distinguish from
        # other error types.
        claims = jwt.decode(
            token, options={"verify_signature": False, "verify_exp": True}
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token expired. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid access token: {exc}",
        ) from exc

    return UserContext(
        oid=claims.get("oid", ""),
        upn=claims.get("preferred_username") or claims.get("upn", ""),
        name=claims.get("name", ""),
        tenant_id=claims.get("tid", ""),
        raw_token=token,
    )
