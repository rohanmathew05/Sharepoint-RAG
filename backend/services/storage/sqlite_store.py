"""SQLite implementation of ConversationStore.

Uses the stdlib `sqlite3` module (no ORM — there's only one implementation
to write right now, so a query-building layer isn't earning its weight
yet) in WAL mode, with a single shared connection guarded by an
`asyncio.Lock` for writes. `sqlite3` itself is blocking, so every call runs
via `asyncio.to_thread` rather than on the event loop.
"""
import asyncio
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.models.documents import Citation
from backend.services.storage.base import ConversationStore, ConversationSummary, StoredMessage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  user_oid TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_oid, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  citations_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
"""

# Truncated at a word boundary where possible so a title never cuts a word
# in half — purely cosmetic, but a half-word title looks broken in a
# sidebar in a way a "..." ellipsis after a full word doesn't.
_TITLE_MAX_CHARS = 60


def _derive_title(first_message: str) -> str:
    text = " ".join(first_message.split())
    if len(text) <= _TITLE_MAX_CHARS:
        return text
    truncated = text[:_TITLE_MAX_CHARS]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    return truncated + "..."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SqliteConversationStore(ConversationStore):
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._lock = asyncio.Lock()

    async def create_conversation(self, user_oid: str, title: str = "") -> ConversationSummary:
        def _do() -> ConversationSummary:
            now = _now()
            conversation_id = uuid.uuid4().hex
            with self._conn:
                self._conn.execute(
                    "INSERT INTO conversations (id, user_oid, title, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, user_oid, title, now, now),
                )
            return ConversationSummary(
                id=conversation_id, title=title, created_at=now, updated_at=now
            )

        async with self._lock:
            return await asyncio.to_thread(_do)

    async def list_conversations(self, user_oid: str) -> list[ConversationSummary]:
        def _do() -> list[ConversationSummary]:
            rows = self._conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_oid = ? ORDER BY updated_at DESC",
                (user_oid,),
            ).fetchall()
            return [ConversationSummary(**dict(row)) for row in rows]

        return await asyncio.to_thread(_do)

    async def get_conversation(
        self, user_oid: str, conversation_id: str
    ) -> ConversationSummary | None:
        def _do() -> ConversationSummary | None:
            row = self._conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations "
                "WHERE user_oid = ? AND id = ?",
                (user_oid, conversation_id),
            ).fetchone()
            return ConversationSummary(**dict(row)) if row else None

        return await asyncio.to_thread(_do)

    async def rename_conversation(self, user_oid: str, conversation_id: str, title: str) -> bool:
        def _do() -> bool:
            with self._conn:
                cur = self._conn.execute(
                    "UPDATE conversations SET title = ?, updated_at = ? "
                    "WHERE user_oid = ? AND id = ?",
                    (title, _now(), user_oid, conversation_id),
                )
            return cur.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_do)

    async def delete_conversation(self, user_oid: str, conversation_id: str) -> bool:
        def _do() -> bool:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM conversations WHERE user_oid = ? AND id = ?",
                    (user_oid, conversation_id),
                )
            return cur.rowcount > 0

        async with self._lock:
            return await asyncio.to_thread(_do)

    async def append_message(
        self,
        user_oid: str,
        conversation_id: str,
        role: str,
        content: str,
        citations: list[Citation] | None = None,
    ) -> None:
        def _do() -> None:
            now = _now()
            citations_json = json.dumps([c.model_dump() for c in (citations or [])])
            with self._conn:
                # Ownership check: only touches a conversation that is both
                # this user's and actually exists — an id for someone
                # else's conversation (or a stale/deleted one) silently
                # persists nothing rather than writing across the boundary.
                owned = self._conn.execute(
                    "SELECT 1 FROM conversations WHERE user_oid = ? AND id = ?",
                    (user_oid, conversation_id),
                ).fetchone()
                if not owned:
                    return
                self._conn.execute(
                    "INSERT INTO messages (id, conversation_id, role, content, citations_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, conversation_id, role, content, citations_json, now),
                )
                self._conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE id = ?",
                    (now, conversation_id),
                )
                if role == "user":
                    row = self._conn.execute(
                        "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
                    ).fetchone()
                    if row and not row["title"]:
                        self._conn.execute(
                            "UPDATE conversations SET title = ? WHERE id = ?",
                            (_derive_title(content), conversation_id),
                        )

        async with self._lock:
            await asyncio.to_thread(_do)

    async def list_messages(self, user_oid: str, conversation_id: str) -> list[StoredMessage]:
        def _do() -> list[StoredMessage]:
            owned = self._conn.execute(
                "SELECT 1 FROM conversations WHERE user_oid = ? AND id = ?",
                (user_oid, conversation_id),
            ).fetchone()
            if not owned:
                return []
            rows = self._conn.execute(
                "SELECT role, content, citations_json, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            ).fetchall()
            return [
                StoredMessage(
                    role=row["role"],
                    content=row["content"],
                    citations=[Citation(**c) for c in json.loads(row["citations_json"])],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

        return await asyncio.to_thread(_do)
