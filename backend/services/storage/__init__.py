"""Wiring for ConversationStore — a FastAPI dependency, not a hardcoded
SQLite import, so routers/tests depend on the interface and can override
this with a fake store (see backend/tests/test_conversations_api.py)."""
from pathlib import Path

from backend.core.config import get_settings
from backend.services.storage.base import ConversationStore
from backend.services.storage.sqlite_store import SqliteConversationStore

_store: ConversationStore | None = None


def get_conversation_store() -> ConversationStore:
    global _store
    if _store is None:
        _store = SqliteConversationStore(Path(get_settings().CHAT_DB_PATH))
    return _store
