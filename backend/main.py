"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import auth, chat, search
from backend.core.config import get_settings

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


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "demo_mode": settings.DEMO_MODE}
