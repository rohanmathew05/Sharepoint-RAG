"""Centralized application settings, loaded from environment variables."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve .env relative to this file (backend/.env), not the
# process's current working directory — the app is meant to be launched
# as `uvicorn backend.main:app` from the repo root (see README), so cwd
# is the repo root, not backend/.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # --- Microsoft Entra ID ---
    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    # Scope the backend requests from Entra ID when exchanging the user's
    # token for a Graph token via the On-Behalf-Of flow.
    GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"
    # Microsoft's Search API (/search/query) expects a "region" in the
    # request body. Graph Explorer's built-in samples default to "US" and
    # a custom app that omits it entirely can get back total: 0 even for
    # content that genuinely exists and matches. ISO 3166-1 alpha-3 code
    # (e.g. "IRL", "GBR") — set this to wherever your tenant's data
    # actually resides if results still look wrong with the default.
    GRAPH_SEARCH_REGION: str = "US"

    # --- Azure OpenAI ---
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_DEPLOYMENT_NAME: str = ""
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"

    # --- App ---
    FRONTEND_ORIGIN: str = "http://localhost:5173"
    MAX_SEARCH_RESULTS: int = 8
    MAX_RAG_CONTEXT_CHARS: int = 12000

    # When true, uses local fixture data instead of calling Microsoft Graph /
    # Azure OpenAI. Useful for running the permission-aware demo without
    # live Azure credentials.
    DEMO_MODE: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
