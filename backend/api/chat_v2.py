"""V2 chat endpoint: LangGraph-orchestrated retrieval with query rewriting
and retrieval evaluation, on top of the same permission-aware
SharePointService used by V1.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.auth.entra import get_current_user
from backend.auth.obo import OBOExchangeError, OBOTokenExpiredError
from backend.models.auth import UserContext
from backend.models.chat import ChatRequest, ChatResponse
from backend.services.graph import GraphAPIError
from backend.services.langgraph_pipeline import LangGraphRAGService

router = APIRouter(prefix="/api/chat/v2", tags=["chat-v2"])
rag_service_v2 = LangGraphRAGService()

logger = logging.getLogger("backend.api.chat_v2")


@router.post("", response_model=ChatResponse)
async def chat_v2(
    request: ChatRequest, user: UserContext = Depends(get_current_user)
) -> ChatResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")
    return await rag_service_v2.answer_question(user, request.question)


@router.post("/stream")
async def chat_v2_stream(
    request: ChatRequest, user: UserContext = Depends(get_current_user)
) -> StreamingResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    async def event_stream():
        # Once the first chunk is sent, the response status is locked in
        # as 200 — an error partway through the pipeline (e.g. the user's
        # Graph session expiring mid-search) can no longer become a real
        # HTTP error status. It's surfaced as a same-shape {"type":
        # "error"} event instead, which the frontend interprets the same
        # way it does the non-streaming endpoint's error responses (see
        # frontend/src/api/client.ts's streamChatMessage).
        try:
            async for event in rag_service_v2.stream_answer(user, request.question):
                yield json.dumps(event) + "\n"
        except OBOTokenExpiredError as exc:
            yield json.dumps(
                {"type": "error", "error_code": "obo_token_expired", "detail": str(exc)}
            ) + "\n"
        except OBOExchangeError as exc:
            yield json.dumps(
                {"type": "error", "error_code": "obo_exchange_failed", "detail": str(exc)}
            ) + "\n"
        except GraphAPIError as exc:
            error_code = "graph_rate_limited" if exc.status_code == 429 else "graph_error"
            yield json.dumps({"type": "error", "error_code": error_code, "detail": str(exc)}) + "\n"
        except Exception:
            logger.exception("Unhandled error while streaming chat response")
            yield json.dumps(
                {
                    "type": "error",
                    "error_code": None,
                    "detail": "Something went wrong. Please try again.",
                }
            ) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")
