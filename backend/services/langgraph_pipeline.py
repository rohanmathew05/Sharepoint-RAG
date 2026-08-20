"""LangGraph-based multi-step RAG orchestration (V2).

Adds query rewriting and retrieval evaluation on top of the V1 single-shot
RAGService: if a SharePoint search comes back empty or the LLM judges the
result irrelevant, the graph rewrites the query and searches again — up
to MAX_RETRIES times — before falling back to generation, instead of
immediately telling the user nothing was found. Every query already
tried is carried in state (`previous_queries`) and fed back into the
rewrite prompt, so each retry is a genuinely different attempt rather
than repeating similar phrasings blind.

    question
       │
       ▼
  analyze_query  (normalize / extract a search query)
       │
       ▼
 classify_intent  (does this actually need a SharePoint search?)
       │
       ├── no (greeting/chitchat) ──▶ answer_conversationally ──▶ END
       │
      yes
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
import logging
from typing import TypedDict

from langgraph.graph import END, StateGraph

from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.models.chat import ChatResponse
from backend.models.documents import Citation, SourceDocument
from backend.services.azure_openai import AzureOpenAIService
from backend.services.sharepoint import SharePointService

MAX_RETRIES = 8

# LangGraph's own step-recursion guard (default 25) counts every node
# transition, not just search attempts: analyze_query + classify_intent
# + generate_answer, plus a search/evaluate/rewrite_query cycle (3 steps)
# per retry after the first. With MAX_RETRIES=8 the worst case exceeds
# the default comfortably, so this is sized to the actual retry budget
# instead of silently hitting LangGraph's unrelated limit first.
_RECURSION_LIMIT = MAX_RETRIES * 3 + 10

logger = logging.getLogger("backend.services.langgraph_pipeline")

# _classify_intent's primary path is a real Azure OpenAI call (see
# AzureOpenAIService.classify_needs_retrieval) — a fixed word-list can't
# make judgment calls the way a classifier can ("what's the deadline"
# vs. "what's up"). This set is only the resilience fallback for when
# that call itself fails, so a classifier hiccup doesn't at least miss
# the obvious greetings. Matched against the whole message, not as a
# substring, so a real question that happens to contain "hi" (e.g.
# "hi-vis vest requirements") isn't misclassified.
_CHITCHAT_MESSAGES = {
    "hi", "hello", "hey", "hiya", "yo", "howdy",
    "thanks", "thank you", "thx", "cheers",
    "bye", "goodbye", "see you",
    "good morning", "good afternoon", "good evening", "good night",
    "how are you", "how's it going", "whats up", "what's up",
    "ok", "okay", "sure", "cool", "nice", "great", "test",
}

_CHITCHAT_REPLY = (
    "Hi! Ask me a question about your company's SharePoint documents — "
    'for example, "What PPE is required for confined space work?" — and '
    "I'll search what you have access to and cite the sources."
)


def _is_chitchat(question: str) -> bool:
    normalized = question.strip().lower().strip("?.!,")
    return normalized in _CHITCHAT_MESSAGES


class RAGState(TypedDict):
    question: str
    user: UserContext
    search_query: str
    needs_retrieval: bool
    documents: list[SourceDocument]
    is_relevant: bool
    prompt_context: str
    retrieval_attempts: int
    max_retries: int
    # Every search query already tried this request, in order. Fed back
    # into the rewrite prompt so each retry is told what already failed
    # instead of guessing blind — without this, a rewrite has no memory
    # and can end up circling similar phrasings across attempts.
    previous_queries: list[str]
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
        graph.add_node("classify_intent", self._classify_intent)
        graph.add_node("answer_conversationally", self._answer_conversationally)
        graph.add_node("search", self._search)
        graph.add_node("evaluate", self._evaluate)
        graph.add_node("rewrite_query", self._rewrite_query)
        graph.add_node("generate_answer", self._generate_answer)

        graph.set_entry_point("analyze_query")
        graph.add_edge("analyze_query", "classify_intent")
        graph.add_conditional_edges(
            "classify_intent",
            self._route_after_classify,
            {"search": "search", "skip": "answer_conversationally"},
        )
        graph.add_edge("search", "evaluate")
        graph.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            {"generate": "generate_answer", "rewrite": "rewrite_query"},
        )
        graph.add_edge("rewrite_query", "search")
        graph.add_edge("generate_answer", END)
        graph.add_edge("answer_conversationally", END)

        return graph.compile()

    # --- nodes -----------------------------------------------------------

    async def _analyze_query(self, state: RAGState) -> dict:
        logger.info("[analyze_query] question=%r", state["question"])
        return {"search_query": state["question"].strip(), "retrieval_attempts": 0}

    async def _classify_intent(self, state: RAGState) -> dict:
        # A greeting ("hi", "thanks", ...) never warrants a SharePoint
        # search — without this, those messages were reaching Graph's
        # search API, which (correctly, per its own relevance ranking)
        # still returns *some* document for almost any query string,
        # producing citations that have nothing to do with what was
        # actually asked. This is a real (cheap, capped) LLM call rather
        # than a fixed word-list, since intent is a judgment call a
        # classifier handles better than an exact match ever could.
        question = state["question"]
        try:
            needs_retrieval = await self.llm.classify_needs_retrieval(question)
        except Exception:
            # Fall back to the heuristic rather than blindly defaulting
            # to "search" — still catches the obvious greetings even
            # when the classifier call itself is unavailable.
            logger.warning("Intent classification failed; falling back to heuristic", exc_info=True)
            needs_retrieval = not _is_chitchat(question)
        logger.info("[classify_intent] question=%r needs_retrieval=%s", question, needs_retrieval)
        return {"needs_retrieval": needs_retrieval}

    def _route_after_classify(self, state: RAGState) -> str:
        route = "search" if state["needs_retrieval"] else "skip"
        logger.info("[route_after_classify] -> %s", route)
        return route

    async def _answer_conversationally(self, state: RAGState) -> dict:
        logger.info("[answer_conversationally] skipping SharePoint search entirely")
        return {"answer": _CHITCHAT_REPLY, "citations": []}

    async def _search(self, state: RAGState) -> dict:
        attempt = state["retrieval_attempts"] + 1
        logger.info(
            "[search] attempt=%d/%d query=%r", attempt, state.get("max_retries", MAX_RETRIES), state["search_query"]
        )
        documents = await self.sharepoint.search(
            state["user"], state["search_query"], max_results=self.settings.MAX_SEARCH_RESULTS
        )
        logger.info(
            "[search] attempt=%d found %d document(s): %s",
            attempt,
            len(documents),
            [d.document_name for d in documents],
        )
        return {
            "documents": documents,
            "retrieval_attempts": attempt,
            "previous_queries": state["previous_queries"] + [state["search_query"]],
        }

    async def _evaluate(self, state: RAGState) -> dict:
        # A presence check ("did search return anything at all") can't
        # tell the difference between "found nothing" and "found the
        # right document, but the snippet doesn't actually contain the
        # specific fact asked for" — a real LLM judgment call can. This
        # is what lets a bad-snippet case retry with a rewritten query
        # instead of confidently generating an unhelpful "not found"
        # answer from context that was never going to answer the
        # question.
        context = self._build_context(state["documents"])
        try:
            is_relevant = await self.llm.evaluate_relevance(state["question"], context)
        except Exception:
            logger.warning("Relevance evaluation failed; defaulting to relevant", exc_info=True)
            is_relevant = len(state["documents"]) > 0
        logger.info(
            "[evaluate] attempt=%d is_relevant=%s context_chars=%d",
            state["retrieval_attempts"],
            is_relevant,
            len(context),
        )
        return {"is_relevant": is_relevant, "prompt_context": context}

    def _route_after_evaluate(self, state: RAGState) -> str:
        if state["is_relevant"]:
            route = "generate"
        elif state["retrieval_attempts"] >= state.get("max_retries", MAX_RETRIES):
            route = "generate"  # give up rewriting, answer with what we have (none)
        else:
            route = "rewrite"
        logger.info(
            "[route_after_evaluate] is_relevant=%s attempt=%d/%d -> %s",
            state["is_relevant"],
            state["retrieval_attempts"],
            state.get("max_retries", MAX_RETRIES),
            route,
        )
        return route

    async def _rewrite_query(self, state: RAGState) -> dict:
        rewritten = await self._llm_rewrite_query(state["question"], state["previous_queries"])
        logger.info("[rewrite_query] %r -> %r", state["search_query"], rewritten)
        return {"search_query": rewritten}

    async def _generate_answer(self, state: RAGState) -> dict:
        documents = state["documents"]
        # Reuse the context _evaluate already built for this same
        # documents list rather than rebuilding it — evaluate always
        # runs immediately before generate_answer on every path.
        context = state["prompt_context"]
        answer = await self.llm.generate_answer(question=state["question"], context=context)
        citations = [
            Citation(
                document_id=d.document_id,
                document_name=d.document_name,
                web_url=d.web_url,
                is_folder=d.is_folder,
                folder_path=d.folder_path,
            )
            for d in documents
        ]
        logger.info(
            "[generate_answer] %d citation(s), answer_chars=%d, total_attempts=%d",
            len(citations),
            len(answer),
            state["retrieval_attempts"],
        )
        return {"answer": answer, "citations": citations}

    # --- helpers -----------------------------------------------------------

    async def _llm_rewrite_query(self, original_question: str, previous_queries: list[str]) -> str:
        # Ask Azure OpenAI for a search query genuinely different from
        # every attempt so far — not just the last one. Without the full
        # history, a rewrite has no memory of what it already tried and
        # can end up circling similar phrasings across retries instead of
        # actually broadening coverage.
        tried = "\n".join(f'- "{q}"' for q in previous_queries)
        prompt_context = (
            f'None of these searches found a relevant result for the '
            f'question "{original_question}":\n{tried}\n\n'
            "Suggest a new search query that is meaningfully different "
            "from all of the above — try different keywords, a broader "
            "or narrower phrasing, or a synonym for a term that may not "
            "match the document's exact wording. Respond with just the "
            "query, no explanation."
        )
        rewritten = await self.llm.generate_answer(question=prompt_context, context="")
        rewritten = rewritten.strip().strip('"')
        return rewritten or previous_queries[-1]

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
        logger.info("=== LangGraph run start: user=%s question=%r ===", user.upn, question)
        initial_state: RAGState = {
            "question": question,
            "user": user,
            "search_query": question,
            "needs_retrieval": True,
            "documents": [],
            "is_relevant": False,
            "prompt_context": "",
            "retrieval_attempts": 0,
            "max_retries": MAX_RETRIES,
            "previous_queries": [],
            "answer": "",
            "citations": [],
        }
        final_state = await self.graph.ainvoke(
            initial_state, config={"recursion_limit": _RECURSION_LIMIT}
        )
        logger.info(
            "=== LangGraph run end: attempts=%d citations=%d queries_tried=%s ===",
            final_state["retrieval_attempts"],
            len(final_state["citations"]),
            final_state["previous_queries"],
        )
        return ChatResponse(
            answer=final_state["answer"],
            citations=final_state["citations"],
            retrieval_attempts=final_state["retrieval_attempts"],
        )
