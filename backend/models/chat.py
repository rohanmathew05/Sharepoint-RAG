"""Pydantic models for the chat / RAG API."""
from pydantic import BaseModel, Field

from backend.models.documents import Citation, SourceDocument


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    question: str
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class ReasoningStep(BaseModel):
    """One stage of the RAG pipeline's real execution trace (see
    LangGraphRAGService), surfaced to the frontend's collapsible
    "chain of thought" display. Not the model's token-level reasoning —
    a factual summary of what the pipeline actually did (which query it
    searched, whether the result was judged relevant, etc.)."""

    kind: str
    label: str
    detail: str | None = None


class RAGContext(BaseModel):
    """The authorised context assembled for a single generation call.

    ``source_documents`` is the complete list of documents whose text was
    placed in the prompt sent to Azure OpenAI. Nothing outside this list
    can appear in the model's context window for this request.
    """

    question: str
    source_documents: list[SourceDocument]
    prompt_context: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    retrieval_attempts: int = 1
    reasoning_steps: list[ReasoningStep] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None
