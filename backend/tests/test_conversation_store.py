"""Verifies SqliteConversationStore's CRUD, ordering, cascade delete,
auto-title derivation, and — critically — per-user isolation (one user
must never be able to read/modify another user's conversation, even by
guessing its id)."""
import pytest

from backend.models.documents import Citation
from backend.services.storage.sqlite_store import SqliteConversationStore

USER_A = "user-a-oid"
USER_B = "user-b-oid"


@pytest.fixture
def store(tmp_path):
    return SqliteConversationStore(tmp_path / "test.db")


@pytest.mark.asyncio
async def test_create_and_list_conversations(store):
    convo = await store.create_conversation(USER_A)
    listed = await store.list_conversations(USER_A)
    assert [c.id for c in listed] == [convo.id]


@pytest.mark.asyncio
async def test_list_conversations_orders_by_most_recently_updated(store):
    first = await store.create_conversation(USER_A)
    second = await store.create_conversation(USER_A)
    # Bumping `first`'s updated_at (via a new message) should move it to
    # the top of the list, ahead of `second` even though it's older.
    await store.append_message(USER_A, first.id, "user", "hello again")

    listed = await store.list_conversations(USER_A)
    assert [c.id for c in listed] == [first.id, second.id]


@pytest.mark.asyncio
async def test_append_message_sets_title_from_first_user_message(store):
    convo = await store.create_conversation(USER_A)
    await store.append_message(USER_A, convo.id, "user", "What PPE is required?")
    await store.append_message(USER_A, convo.id, "assistant", "Here's what I found...")

    updated = await store.get_conversation(USER_A, convo.id)
    assert updated.title == "What PPE is required?"


@pytest.mark.asyncio
async def test_title_truncates_long_first_message_at_word_boundary(store):
    convo = await store.create_conversation(USER_A)
    long_message = "word " * 30  # well over the 60-char cap
    await store.append_message(USER_A, convo.id, "user", long_message)

    updated = await store.get_conversation(USER_A, convo.id)
    assert len(updated.title) <= 63  # 60 chars + "..."
    assert updated.title.endswith("...")
    assert not updated.title[:-3].endswith(" ")  # no half-word before the ellipsis


@pytest.mark.asyncio
async def test_list_messages_returns_in_order_with_citations(store):
    convo = await store.create_conversation(USER_A)
    citation = Citation(document_id="doc-1", document_name="Doc.pdf", web_url="https://x/doc.pdf")
    await store.append_message(USER_A, convo.id, "user", "question one")
    await store.append_message(USER_A, convo.id, "assistant", "answer one", [citation])

    messages = await store.list_messages(USER_A, convo.id)
    assert [m.content for m in messages] == ["question one", "answer one"]
    assert messages[1].citations == [citation]


@pytest.mark.asyncio
async def test_rename_and_delete_conversation(store):
    convo = await store.create_conversation(USER_A)

    assert await store.rename_conversation(USER_A, convo.id, "New title") is True
    updated = await store.get_conversation(USER_A, convo.id)
    assert updated.title == "New title"

    assert await store.delete_conversation(USER_A, convo.id) is True
    assert await store.get_conversation(USER_A, convo.id) is None


@pytest.mark.asyncio
async def test_delete_conversation_cascades_to_messages(store):
    convo = await store.create_conversation(USER_A)
    await store.append_message(USER_A, convo.id, "user", "hello")

    await store.delete_conversation(USER_A, convo.id)

    # The conversation is gone, so list_messages (which checks ownership
    # first) returns empty rather than orphaned rows.
    assert await store.list_messages(USER_A, convo.id) == []


@pytest.mark.asyncio
async def test_user_cannot_read_another_users_conversation(store):
    convo = await store.create_conversation(USER_A)
    await store.append_message(USER_A, convo.id, "user", "secret question")

    assert await store.get_conversation(USER_B, convo.id) is None
    assert await store.list_messages(USER_B, convo.id) == []
    assert await store.list_conversations(USER_B) == []


@pytest.mark.asyncio
async def test_user_cannot_rename_or_delete_another_users_conversation(store):
    convo = await store.create_conversation(USER_A)

    assert await store.rename_conversation(USER_B, convo.id, "hijacked") is False
    assert await store.delete_conversation(USER_B, convo.id) is False

    # Untouched from USER_A's perspective.
    still_there = await store.get_conversation(USER_A, convo.id)
    assert still_there is not None
    assert still_there.title != "hijacked"


@pytest.mark.asyncio
async def test_user_cannot_append_message_to_another_users_conversation(store):
    convo = await store.create_conversation(USER_A)

    await store.append_message(USER_B, convo.id, "user", "smuggled message")

    messages = await store.list_messages(USER_A, convo.id)
    assert messages == []
