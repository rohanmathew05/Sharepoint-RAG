"""FastAPI application entrypoint."""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.api import auth, chat, search
from backend.auth.obo import OBOExchangeError, OBOTokenExpiredError
from backend.core.config import get_settings
from backend.services.graph import GraphAPIError

settings = get_settings()

app = FastAPI(
    title="Permission-Aware SharePoint RAG Assistant",
    description=(
        "Retrieves SharePoint content within the authenticated user's "
        "existing Microsoft 365 permissions and grounds Azure OpenAI "
        "responses in it."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(search.router)


@app.exception_handler(OBOTokenExpiredError)
async def obo_token_expired_handler(request: Request, exc: OBOTokenExpiredError) -> JSONResponse:
    # Mid-session token expiry: tell the frontend to re-authenticate
    # rather than showing a generic error. See docs/SETUP.md's "OBO token
    # expiry" section.
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc), "error_code": "obo_token_expired"},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(OBOExchangeError)
async def obo_exchange_error_handler(request: Request, exc: OBOExchangeError) -> JSONResponse:
    # Not a re-auth situation (bad app registration, missing admin
    # consent, transient Entra ID error) — surface as a server error, not
    # a silent 500 with no explanation.
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "error_code": "obo_exchange_failed"},
    )


@app.exception_handler(GraphAPIError)
async def graph_api_error_handler(request: Request, exc: GraphAPIError) -> JSONResponse:
    headers = {"Retry-After": exc.retry_after} if exc.retry_after else {}
    status_code = 429 if exc.status_code == 429 else 502
    error_code = "graph_rate_limited" if exc.status_code == 429 else "graph_error"
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(exc), "error_code": error_code},
        headers=headers,
    )


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "demo_mode": settings.DEMO_MODE}
