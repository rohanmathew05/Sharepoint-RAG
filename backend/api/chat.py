"""Chat endpoint (V1, non-streaming). The frontend only calls
/api/chat/v2/stream (see chat_v2.py) — this endpoint doesn't persist
messages or participate in conversation history."""
from fastapi import APIRouter, Depends, HTTPException

from backend.auth.entra import get_current_user
from backend.models.auth import UserContext
from backend.models.chat import ChatRequest, ChatResponse
from backend.services.rag import RAGService

router = APIRouter(prefix="/api/chat", tags=["chat"])
rag_service = RAGService()


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest, user: UserContext = Depends(get_current_user)
) -> ChatResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    return await rag_service.answer_question(user, request.question)
