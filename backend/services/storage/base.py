"""Storage abstraction for persisted conversations/messages.

Everything above this layer (routers, the RAG pipeline) depends only on
`ConversationStore` — never on `SqliteConversationStore` directly — so the
concrete backend can be swapped later (e.g. for Postgres) without touching
route or service code. Every method takes `user_oid` and is expected to
filter by it: this is the ownership check that keeps one user from ever
reading or modifying another user's conversations, not something enforced
separately in the router layer.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from pydantic import BaseModel, Field

from backend.models.documents import Citation


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class StoredMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    citations: list[Citation] = Field(default_factory=list)
    created_at: datetime


class ConversationStore(ABC):
    @abstractmethod
    async def create_conversation(self, user_oid: str, title: str = "") -> ConversationSummary: ...

    @abstractmethod
    async def list_conversations(self, user_oid: str) -> list[ConversationSummary]: ...

    @abstractmethod
    async def get_conversation(
        self, user_oid: str, conversation_id: str
    ) -> ConversationSummary | None: ...

    @abstractmethod
    async def rename_conversation(self, user_oid: str, conversation_id: str, title: str) -> bool:
        """Returns False (no-op) if the conversation doesn't exist or isn't
        owned by user_oid, rather than raising — same ownership-is-silent
        posture as the rest of this interface."""
        ...

    @abstractmethod
    async def delete_conversation(self, user_oid: str, conversation_id: str) -> bool:
        """Returns False (no-op) if the conversation doesn't exist or isn't
        owned by user_oid."""
        ...

    @abstractmethod
    async def append_message(
        self,
        user_oid: str,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[Citation] | None = None,
    ) -> None: ...

    @abstractmethod
    async def list_messages(self, user_oid: str, conversation_id: str) -> list[StoredMessage]: ...
