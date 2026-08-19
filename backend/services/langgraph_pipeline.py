"""LangGraph-based multi-step RAG orchestration (V2).

Adds query rewriting and retrieval evaluation on top of the V1 single-shot
RAGService: if the first SharePoint search comes back empty or too thin,
the graph rewrites the query and searches again (bounded by max_retries)
before falling back to generation, instead of immediately telling the
user nothing was found.

    question
       │
       ▼
  analyze_query  (normalize / extract a search query)
       │
       ▼
    search  ◀────────────────┐  (permission-aware SharePoint search)
       │                      │
       ▼                      │
   evaluate                   │
       │                      │
  relevant?──── no, retries left ──▶ rewrite_query ──┘
       │
      yes / retries exhausted
       │
       ▼
 generate_answer
       │
       ▼
      END

The permission boundary is unchanged from V1: every `search` node call
still goes through `SharePointService.search()`, which is gated by an
OBO-derived Graph token for the requesting user. Rewriting the query and
retrying never bypasses that — it only changes what gets searched for,
not who is allowed to see the results.
"""
from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.models.chat import ChatResponse
from backend.models.documents import Citation, SourceDocument
from backend.services.azure_openai import AzureOpenAIService
from backend.services.sharepoint import SharePointService

MAX_RETRIES = 2

# A tiny stand-in for "ask the LLM to rewrite the query" — broadens the
# query by dropping the least-specific leading word so a second search
# attempt can surface partial matches. Real deployments should replace
# this with an Azure OpenAI call (see _llm_rewrite_query below).
_GENERIC_LEADING_WORDS = {"what", "how", "when", "where", "is", "are", "does", "the", "a"}


class RAGState(TypedDict):
    question: str
    user: UserContext
    search_query: str
    documents: list[SourceDocument]
    is_relevant: bool
    retrieval_attempts: int
    max_retries: int
    answer: str
    citations: list[Citation]


class LangGraphRAGService:
    """Multi-step RAG pipeline built with LangGraph.

    Drop-in alternative to RAGService (backend/services/rag.py) — same
    inputs/outputs, more sophisticated retrieval in between.
    """

    def __init__(self):
        self.settings = get_settings()
        self.sharepoint = SharePointService()
        self.llm = AzureOpenAIService()
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RAGState)

        graph.add_node("analyze_query", self._analyze_query)
        graph.add_node("search", self._search)
        graph.add_node("evaluate", self._evaluate)
        graph.add_node("rewrite_query", self._rewrite_query)
        graph.add_node("generate_answer", self._generate_answer)

        graph.set_entry_point("analyze_query")
        graph.add_edge("analyze_query", "search")
        graph.add_edge("search", "evaluate")
        graph.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            {"generate": "generate_answer", "rewrite": "rewrite_query"},
        )
        graph.add_edge("rewrite_query", "search")
        graph.add_edge("generate_answer", END)

        return graph.compile()

    # --- nodes -----------------------------------------------------------

    async def _analyze_query(self, state: RAGState) -> dict:
        return {"search_query": state["question"].strip(), "retrieval_attempts": 0}

    async def _search(self, state: RAGState) -> dict:
        documents = await self.sharepoint.search(
            state["user"], state["search_query"], max_results=self.settings.MAX_SEARCH_RESULTS
        )
        return {
            "documents": documents,
            "retrieval_attempts": state["retrieval_attempts"] + 1,
        }

    async def _evaluate(self, state: RAGState) -> dict:
        # A minimal relevance check: did the search return anything at
        # all? A production system could score each document's snippet
        # against the question (e.g. with an LLM judge or embedding
        # similarity) instead of this presence check.
        return {"is_relevant": len(state["documents"]) > 0}

    def _route_after_evaluate(self, state: RAGState) -> str:
        if state["is_relevant"]:
            return "generate"
        if state["retrieval_attempts"] >= state.get("max_retries", MAX_RETRIES):
            return "generate"  # give up rewriting, answer with what we have (none)
        return "rewrite"

    async def _rewrite_query(self, state: RAGState) -> dict:
        rewritten = await self._llm_rewrite_query(state["question"], state["search_query"])
        return {"search_query": rewritten}

    async def _generate_answer(self, state: RAGState) -> dict:
        documents = state["documents"]
        context = self._build_context(documents)
        answer = await self.llm.generate_answer(question=state["question"], context=context)
        citations = [
            Citation(document_id=d.document_id, document_name=d.document_name, web_url=d.web_url)
            for d in documents
        ]
        return {"answer": answer, "citations": citations}

    # --- helpers -----------------------------------------------------------

    async def _llm_rewrite_query(self, original_question: str, previous_query: str) -> str:
        if not self.settings.DEMO_MODE:
            # Real deployment: ask Azure OpenAI for a broader/alternate
            # phrasing of the search query.
            prompt_context = (
                f'The search "{previous_query}" returned no relevant SharePoint '
                f'results for the question "{original_question}". Suggest a '
                "broader or differently-phrased search query (respond with "
                "just the query, no explanation)."
            )
            rewritten = await self.llm.generate_answer(question=prompt_context, context="")
            return rewritten.strip().strip('"') or previous_query

        # DEMO_MODE fallback: drop generic leading words and keep dropping
        # one word per attempt so the second search is broader than the
        # first, without needing a live LLM call.
        words = previous_query.split()
        while words and words[0].lower().strip("?.,!") in _GENERIC_LEADING_WORDS:
            words.pop(0)
        if len(words) > 1:
            words.pop(0)
        return " ".join(words) or original_question

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

    # --- public API --------------------------------------------------------

    async def answer_question(self, user: UserContext, question: str) -> ChatResponse:
        initial_state: RAGState = {
            "question": question,
            "user": user,
            "search_query": question,
            "documents": [],
            "is_relevant": False,
            "retrieval_attempts": 0,
            "max_retries": MAX_RETRIES,
            "answer": "",
            "citations": [],
        }
        final_state = await self.graph.ainvoke(initial_state)
        return ChatResponse(
            answer=final_state["answer"],
            citations=final_state["citations"],
            retrieval_attempts=final_state["retrieval_attempts"],
        )
