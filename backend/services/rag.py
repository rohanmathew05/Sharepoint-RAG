"""Core RAG orchestration.

Flow: authenticated user's question -> permission-aware SharePoint search
(SharePointService, itself gated by the user's OBO Graph token) -> prompt
context assembly -> Azure OpenAI generation -> answer + citations.

The set of documents that can ever reach Azure OpenAI for a given request
is exactly SharePointService.search()'s return value for *that user*.
Nothing is added afterward, and nothing bypasses this path.
"""
from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.models.chat import ChatResponse, RAGContext
from backend.models.documents import Citation, SourceDocument
from backend.services.azure_openai import AzureOpenAIService
from backend.services.sharepoint import SharePointService


class RAGService:
    def __init__(self):
        self.settings = get_settings()
        self.sharepoint = SharePointService()
        self.llm = AzureOpenAIService()

    def _build_context(self, documents: list[SourceDocument]) -> str:
        parts = []
        total_chars = 0
        for doc in documents:
            block = f"[{doc.document_name}]\n{doc.relevant_content}"
            if total_chars + len(block) > self.settings.MAX_RAG_CONTEXT_CHARS:
                break
            parts.append(block)
            total_chars += len(block)
        return "\n\n".join(parts)

    async def answer_question(self, user: UserContext, question: str) -> ChatResponse:
        documents = await self.sharepoint.search(
            user, question, max_results=self.settings.MAX_SEARCH_RESULTS
        )

        rag_context = RAGContext(
            question=question,
            source_documents=documents,
            prompt_context=self._build_context(documents),
        )

        answer = await self.llm.generate_answer(
            question=rag_context.question, context=rag_context.prompt_context
        )

        citations = [
            Citation(
                document_id=doc.document_id,
                document_name=doc.document_name,
                web_url=doc.web_url,
            )
            for doc in documents
        ]

        return ChatResponse(answer=answer, citations=citations, retrieval_attempts=1)
