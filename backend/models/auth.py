"""Pydantic models for the authenticated user context."""
from pydantic import BaseModel


class UserContext(BaseModel):
    """The authenticated user, derived from a validated Entra ID access token.

    This is never trusted for permission decisions on its own — it only
    identifies *who* is asking. Actual document access is always
    re-checked by Microsoft Graph using the user's own delegated
    (On-Behalf-Of) token, not by anything stored here.
    """

    oid: str
    upn: str
    name: str
    tenant_id: str
    raw_token: str = ""  # the inbound bearer token; never returned to the client
