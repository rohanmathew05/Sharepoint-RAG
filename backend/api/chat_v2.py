"""V2 chat endpoint: LangGraph-orchestrated retrieval with query rewriting
and retrieval evaluation, on top of the same permission-aware
SharePointService used by V1.
"""
from fastapi import APIRouter, Depends, HTTPException

from backend.auth.entra import get_current_user
from backend.models.auth import UserContext
from backend.models.chat import ChatRequest, ChatResponse
from backend.services.langgraph_pipeline import LangGraphRAGService

router = APIRouter(prefix="/api/chat/v2", tags=["chat-v2"])
rag_service_v2 = LangGraphRAGService()


@router.post("", response_model=ChatResponse)
async def chat_v2(
    request: ChatRequest, user: UserContext = Depends(get_current_user)
) -> ChatResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    return await rag_service_v2.answer_question(user, request.question)
