"""Chat endpoint: the main RAG entry point used by the frontend."""
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
