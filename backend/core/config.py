"""Centralized application settings, loaded from environment variables."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Microsoft Entra ID ---
    ENTRA_TENANT_ID: str = ""
    ENTRA_CLIENT_ID: str = ""
    ENTRA_CLIENT_SECRET: str = ""
    # Scope the backend requests from Entra ID when exchanging the user's
    # token for a Graph token via the On-Behalf-Of flow.
    GRAPH_SCOPE: str = "https://graph.microsoft.com/.default"

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
