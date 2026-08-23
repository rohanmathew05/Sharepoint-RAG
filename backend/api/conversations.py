"""CRUD over persisted conversations — the "session history" sidebar's API.
Message persistence itself happens in backend/api/chat_v2.py as part of
answering a question; this router only lists/reads/renames/deletes."""
from fastapi import APIRouter, Depends, HTTPException

from backend.auth.entra import get_current_user
from backend.models.auth import UserContext
from backend.models.chat import (
    ChatMessage,
    ConversationDetail,
    ConversationSummary,
    CreateConversationResponse,
    RenameConversationRequest,
)
from backend.services.storage import get_conversation_store
from backend.services.storage.base import ConversationStore

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> list[ConversationSummary]:
    return await store.list_conversations(user.oid)


@router.post("", response_model=CreateConversationResponse, status_code=201)
async def create_conversation(
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> CreateConversationResponse:
    convo = await store.create_conversation(user.oid)
    return CreateConversationResponse(id=convo.id)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationDetail:
    convo = await store.get_conversation(user.oid, conversation_id)
    if convo is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await store.list_messages(user.oid, conversation_id)
    return ConversationDetail(
        **convo.model_dump(),
        messages=[
            ChatMessage(role=m.role, content=m.content, citations=m.citations) for m in messages
        ],
    )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    body: RenameConversationRequest,
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ConversationSummary:
    renamed = await store.rename_conversation(user.oid, conversation_id, body.title)
    if not renamed:
        raise HTTPException(status_code=404, detail="Conversation not found")
    convo = await store.get_conversation(user.oid, conversation_id)
    assert convo is not None  # just renamed it above
    return convo


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> None:
    deleted = await store.delete_conversation(user.oid, conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
