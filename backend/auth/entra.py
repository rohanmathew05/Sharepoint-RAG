"""Validates inbound Microsoft Entra ID access tokens and derives UserContext.

Signature verification against Entra ID's JWKS is intentionally left for
production hardening (see docs/SETUP.md) — this decodes claims for the
OBO exchange, which itself is what actually proves the token is valid
(Entra ID rejects a forged token during the exchange). `verify_exp` IS
enabled, though: an expired frontend token must be rejected here with a
clean 401 rather than reaching the OBO exchange, where MSAL's failure is
harder to distinguish from other error types.
"""
import jwt
from fastapi import HTTPException, Request, status

from backend.models.auth import UserContext


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
    token = _get_bearer_token(request)
    try:
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
