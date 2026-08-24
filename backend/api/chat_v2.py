"""V2 chat endpoint: LangGraph-orchestrated retrieval with query rewriting
and retrieval evaluation, on top of the same permission-aware
SharePointService used by V1.

Also owns conversation persistence: if the request doesn't carry a
conversation_id, one is created; the incoming question and the generated
answer are both persisted to it, and prior messages in that conversation
are loaded and threaded into the RAG pipeline as multi-turn context (see
backend/services/langgraph_pipeline.py). The server is authoritative for
history here, not the client-supplied conversation_history field on
ChatRequest — see that field's docstring in backend/models/chat.py.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from backend.auth.entra import get_current_user
from backend.auth.obo import OBOExchangeError, OBOTokenExpiredError
from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.models.chat import ChatMessage, ChatRequest, ChatResponse
from backend.models.documents import Citation
from backend.services.graph import GraphAPIError
from backend.services.langgraph_pipeline import LangGraphRAGService
from backend.services.storage import get_conversation_store
from backend.services.storage.base import ConversationStore

router = APIRouter(prefix="/api/chat/v2", tags=["chat-v2"])
rag_service_v2 = LangGraphRAGService()

logger = logging.getLogger("backend.api.chat_v2")


async def _resolve_conversation_and_history(
    store: ConversationStore, user: UserContext, request: ChatRequest
) -> tuple[str, list[ChatMessage]]:
    """Ensures a conversation exists, loads its prior messages (capped to
    MAX_HISTORY_MESSAGES), and persists the incoming user message to it.
    Returns (conversation_id, history) where history does NOT yet include
    the just-persisted user message — it's exactly what the LLM should see
    as prior context.
    """
    conversation_id = request.conversation_id
    if conversation_id is None:
        conversation = await store.create_conversation(user.oid)
        conversation_id = conversation.id
    else:
        conversation = await store.get_conversation(user.oid, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")

    stored_history = await store.list_messages(user.oid, conversation_id)
    max_history = get_settings().MAX_HISTORY_MESSAGES
    history = [
        ChatMessage(role=m.role, content=m.content) for m in stored_history[-max_history:]
    ]

    await store.append_message(user.oid, conversation_id, "user", request.question)

    return conversation_id, history


@router.post("", response_model=ChatResponse)
async def chat_v2(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
) -> ChatResponse:
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    conversation_id, history = await _resolve_conversation_and_history(store, user, request)
    response = await rag_service_v2.answer_question(user, request.question, history=history)
    response.conversation_id = conversation_id
    await store.append_message(
        user.oid, conversation_id, "assistant", response.answer, response.citations
    )
    return response


@router.post("/stream")
async def chat_v2_stream(
    request: ChatRequest,
    user: UserContext = Depends(get_current_user),
    store: ConversationStore = Depends(get_conversation_store),
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
            conversation_id, history = await _resolve_conversation_and_history(
                store, user, request
            )
            # Emitted before generation starts so the frontend can adopt a
            # freshly-created conversation id immediately, rather than only
            # finding out at the very end via the "done" event.
            yield json.dumps({"type": "conversation", "id": conversation_id}) + "\n"

            full_answer = ""
            citations = []
            async for event in rag_service_v2.stream_answer(
                user, request.question, history=history
            ):
                if event["type"] == "done":
                    full_answer = event["answer"]
                    citations = event["citations"]
                    event = {**event, "conversation_id": conversation_id}
                yield json.dumps(event) + "\n"

            # Only persisted on a successful finish — an error path below
            # never reaches here, so a broken/partial reply is never saved
            # (a retry/reload would otherwise show garbled history).
            await store.append_message(
                user.oid,
                conversation_id,
                "assistant",
                full_answer,
                [Citation(**c) for c in citations],
            )
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
