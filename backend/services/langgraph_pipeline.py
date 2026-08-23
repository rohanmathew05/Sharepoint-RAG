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
from typing import AsyncIterator, TypedDict

from langgraph.graph import END, StateGraph

from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.models.chat import ChatResponse, ReasoningStep
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

_FALLBACK_CHITCHAT_REPLY = (
    "Hi! Ask me a question about your company's SharePoint documents — "
    'for example, "What PPE is required for confined space work?" — and '
    "I'll search what you have access to and cite the sources."
)

_FALLBACK_CLARIFICATION_REPLY = (
    "I couldn't find anything in the documents I have access to that "
    "answers this. Could you share a bit more detail — an exact "
    "document or site name, a reference number, or a different way of "
    "describing what you're looking for?"
)


def _is_chitchat(question: str) -> bool:
    normalized = question.strip().lower().strip("?.!,")
    return normalized in _CHITCHAT_MESSAGES


# Cheap pre-filter so classify_entities (a real LLM call) is only ever
# paid for on questions that already look like they might be comparing
# multiple things — the common single-topic question never triggers it.
_COMPARISON_HINTS = (
    "compare", "comparing", "comparison", " vs ", " vs.", " versus ",
    "difference between", "differences between", "differ from",
    " or ", " and ",
)


def _looks_like_comparison(question: str) -> bool:
    normalized = f" {question.strip().lower()} "
    return any(hint in normalized for hint in _COMPARISON_HINTS)


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
    # The richest non-empty (documents, context) pair seen across every
    # attempt, tracked separately from `documents`/`prompt_context` (which
    # only ever hold the *most recent* attempt). Without this, an attempt
    # that finds the right document but gets marked not-relevant, followed
    # by a rewritten query that finds nothing, silently loses that earlier
    # find — generate_answer would see only the empty final attempt and
    # fall straight to a "couldn't find anything" clarification even
    # though something plausible was found along the way.
    best_documents: list[SourceDocument]
    best_context: str
    answer: str
    citations: list[Citation]
    # Real execution trace surfaced to the frontend's collapsible
    # "chain of thought" display — see ReasoningStep. Appended to (never
    # mutated in place) by each node, the same way previous_queries is.
    reasoning_steps: list[dict]
    # Set by _decide_generation (via _prepare_generation for the
    # streaming graph, or inline in _generate_answer for the non-streaming
    # one) so the streaming path knows what to generate without having to
    # re-derive it from is_relevant/best_context itself.
    generation_mode: str
    generation_context: str
    # Set by _analyze_query: whether this question is asking to compare
    # two or more distinct named things, and if so what they are. When
    # True, the graph routes to _compare_search instead of the normal
    # single-query search/evaluate/rewrite loop.
    is_comparison: bool
    entities: list[str]
    # Per-entity search results/misses from _compare_search, kept
    # separate from `documents` (which holds the flat merged/deduped
    # list for citations) so _build_comparison_context can label each
    # entity's own section — including an explicit "not found" note for
    # an entity with zero results, instead of silently dropping it.
    entity_documents: dict[str, list[SourceDocument]]
    entity_found: dict[str, bool]


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
        # Same graph, but stops right before the final LLM call (see
        # _prepare_generation / _prepare_conversational) instead of
        # generating the full answer in one shot — stream_answer() does
        # the actual (streamed) generation itself once this finishes, so
        # token deltas can be yielded as they arrive.
        self.graph_stream = self._build_graph(streaming=True)

    def _build_graph(self, streaming: bool = False):
        graph = StateGraph(RAGState)

        graph.add_node("analyze_query", self._analyze_query)
        graph.add_node("classify_intent", self._classify_intent)
        graph.add_node("search", self._search)
        graph.add_node("evaluate", self._evaluate)
        graph.add_node("rewrite_query", self._rewrite_query)
        graph.add_node("compare_search", self._compare_search)
        if streaming:
            graph.add_node("answer_conversationally", self._prepare_conversational)
            graph.add_node("generate_answer", self._prepare_generation)
        else:
            graph.add_node("answer_conversationally", self._answer_conversationally)
            graph.add_node("generate_answer", self._generate_answer)

        graph.set_entry_point("analyze_query")
        graph.add_edge("analyze_query", "classify_intent")
        graph.add_conditional_edges(
            "classify_intent",
            self._route_after_classify,
            {"search": "search", "compare": "compare_search", "skip": "answer_conversationally"},
        )
        graph.add_edge("search", "evaluate")
        graph.add_conditional_edges(
            "evaluate",
            self._route_after_evaluate,
            {"generate": "generate_answer", "rewrite": "rewrite_query"},
        )
        graph.add_edge("rewrite_query", "search")
        graph.add_edge("compare_search", "generate_answer")
        graph.add_edge("generate_answer", END)
        graph.add_edge("answer_conversationally", END)

        return graph.compile()

    # --- nodes -----------------------------------------------------------

    @staticmethod
    def _step(kind: str, label: str, detail: str | None = None) -> dict:
        return {"kind": kind, "label": label, "detail": detail}

    async def _analyze_query(self, state: RAGState) -> dict:
        question = state["question"]
        logger.info("[analyze_query] question=%r", question)
        step = self._step("understand", "Understanding the question")

        is_comparison = False
        entities: list[str] = []
        if _looks_like_comparison(question):
            try:
                extraction = await self.llm.classify_entities(question)
                if extraction.is_comparison and len(extraction.entities) >= 2:
                    is_comparison = True
                    entities = extraction.entities
            except Exception:
                logger.warning("Entity classification failed; falling back to single search", exc_info=True)
        logger.info("[analyze_query] is_comparison=%s entities=%s", is_comparison, entities)

        return {
            "search_query": question.strip(),
            "retrieval_attempts": 0,
            "is_comparison": is_comparison,
            "entities": entities,
            "reasoning_steps": state["reasoning_steps"] + [step],
        }

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
        if not state["needs_retrieval"]:
            route = "skip"
        elif state.get("is_comparison"):
            route = "compare"
        else:
            route = "search"
        logger.info("[route_after_classify] -> %s", route)
        return route

    async def _prepare_conversational(self, state: RAGState) -> dict:
        logger.info("[prepare_conversational] skipping SharePoint search entirely")
        step = self._step("skip", "Answering directly", "No document search needed for this message.")
        return {
            "generation_mode": "conversational",
            "reasoning_steps": state["reasoning_steps"] + [step],
        }

    async def _answer_conversationally(self, state: RAGState) -> dict:
        prepared = await self._prepare_conversational(state)
        try:
            answer = await self.llm.generate_conversational_reply(state["question"])
        except Exception:
            logger.warning("Conversational reply generation failed; using fallback", exc_info=True)
            answer = _FALLBACK_CHITCHAT_REPLY
        return {
            "answer": answer or _FALLBACK_CHITCHAT_REPLY,
            "citations": [],
            "reasoning_steps": prepared["reasoning_steps"],
        }

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
        step = self._step(
            "search",
            f'Searching for "{state["search_query"]}"',
            f"Found {len(documents)} document(s)."
            if documents
            else "No documents found.",
        )
        return {
            "documents": documents,
            "retrieval_attempts": attempt,
            "previous_queries": state["previous_queries"] + [state["search_query"]],
            "reasoning_steps": state["reasoning_steps"] + [step],
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
        result: dict = {"is_relevant": is_relevant, "prompt_context": context}

        # Keep the richest context ever found, not just the latest — a
        # later rewrite that finds nothing shouldn't erase an earlier
        # attempt that actually found something. This is also a hedge
        # against a false-negative relevance verdict: the "not relevant"
        # judgment might be wrong, and if every later attempt comes back
        # empty, this is the best material generate_answer will ever get.
        if len(context) > len(state.get("best_context", "")):
            result["best_documents"] = state["documents"]
            result["best_context"] = context

        if is_relevant:
            detail = "Relevant — using these documents to answer."
        elif state["retrieval_attempts"] >= state.get("max_retries", MAX_RETRIES):
            detail = "Not relevant, but no retries left — using the best result found."
        else:
            detail = "Not directly relevant — trying another search."
        step = self._step("evaluate", "Checking relevance", detail)
        result["reasoning_steps"] = state["reasoning_steps"] + [step]

        return result

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

    async def _compare_search(self, state: RAGState) -> dict:
        # A comparison question ("compare X and Y") is really N
        # independent lookups, not one blended search — a single Graph
        # query for the combined text often can't surface unrelated
        # documents in the same top-K result set. So each entity gets
        # its own bounded search+evaluate+rewrite loop here, and the
        # results are merged (never overwritten) into one context
        # labeled per entity, including an explicit note when an
        # entity's search comes back empty.
        entities = state["entities"]
        n = max(len(entities), 1)
        per_entity_results = max(self.settings.MAX_SEARCH_RESULTS // n, 1)

        entity_documents: dict[str, list[SourceDocument]] = {}
        entity_found: dict[str, bool] = {}
        reasoning_steps = list(state["reasoning_steps"])
        previous_queries = list(state["previous_queries"])
        total_attempts = 0

        for entity in entities:
            query = entity
            tried: list[str] = []
            docs: list[SourceDocument] = []
            for attempt in range(1, self.settings.MAX_RETRIES_PER_ENTITY + 1):
                docs = await self.sharepoint.search(
                    state["user"], query, max_results=per_entity_results
                )
                tried.append(query)
                previous_queries.append(query)
                total_attempts += 1
                relevant = False
                if docs:
                    context = self._build_context(docs)
                    try:
                        relevant = await self.llm.evaluate_relevance(
                            f"{state['question']} (specifically regarding {entity})", context
                        )
                    except Exception:
                        logger.warning("Relevance evaluation failed during comparison search; defaulting to relevant", exc_info=True)
                        relevant = True
                # One reasoning step per attempt (not just a final summary
                # per entity) — mirrors _search's behavior on the
                # single-topic path, so a rewrite/retry is actually
                # visible in the UI instead of looking like it never
                # happened.
                reasoning_steps.append(self._step(
                    "search",
                    f'Searching for "{query}"',
                    f"Found {len(docs)} document(s)." if docs else "No documents found.",
                ))
                if relevant:
                    break
                if attempt < self.settings.MAX_RETRIES_PER_ENTITY:
                    query = await self._llm_rewrite_query(entity, tried)

            entity_documents[entity] = docs
            entity_found[entity] = bool(docs)
            logger.info(
                "[compare_search] entity=%r found=%d query=%r attempts=%d",
                entity, len(docs), query, len(tried),
            )

        merged_documents = self._merge_and_dedupe(entity_documents)
        context = self._build_comparison_context(entity_documents, entity_found)

        return {
            "entity_documents": entity_documents,
            "entity_found": entity_found,
            "documents": merged_documents,
            "prompt_context": context,
            "best_documents": merged_documents,
            "best_context": context,
            "is_relevant": any(entity_found.values()),
            "retrieval_attempts": state["retrieval_attempts"] + total_attempts,
            "previous_queries": previous_queries,
            "reasoning_steps": reasoning_steps,
        }

    @staticmethod
    def _merge_and_dedupe(entity_documents: dict[str, list[SourceDocument]]) -> list[SourceDocument]:
        seen_ids: set[str] = set()
        merged: list[SourceDocument] = []
        for docs in entity_documents.values():
            for doc in docs:
                if doc.document_id in seen_ids:
                    continue
                seen_ids.add(doc.document_id)
                merged.append(doc)
        return merged

    def _build_comparison_context(
        self, entity_documents: dict[str, list[SourceDocument]], entity_found: dict[str, bool]
    ) -> str:
        n = max(len(entity_documents), 1)
        per_entity_budget = self.settings.MAX_RAG_CONTEXT_CHARS // n

        sections = []
        for entity, docs in entity_documents.items():
            if not entity_found.get(entity):
                sections.append(f'=== {entity} ===\n(No documents found for "{entity}".)')
                continue
            parts = []
            total_chars = 0
            for doc in docs:
                block = f"[{doc.document_name}]\n{doc.relevant_content}"
                if total_chars + len(block) > per_entity_budget:
                    break
                parts.append(block)
                total_chars += len(block)
            sections.append(f"=== {entity} ===\n" + "\n\n".join(parts))
        return "\n\n".join(sections)

    def _decide_generation(self, state: RAGState) -> dict:
        """Pure decision logic shared by the non-streaming _generate_answer
        node and the streaming graph's _prepare_generation node: which mode
        to generate in, and — for a grounded answer — the context and
        citations to use. Never calls the LLM itself, so the streaming
        path can run this, then stream tokens outside the graph.

        Arriving here with is_relevant=False means the *last* attempt
        wasn't judged relevant — but that doesn't mean nothing useful was
        ever found. An earlier attempt can find the right document and
        get marked not-relevant, and a later rewrite can then find nothing
        at all; without best_documents/best_context, that earlier find
        would be silently lost and this would always fall to a
        clarification even when real candidate content exists. Only when
        nothing was ever found (best_context still empty) do we skip
        straight to asking for more detail.
        """
        if not state["is_relevant"] and not state.get("best_context"):
            return {"generation_mode": "clarification", "citations": []}

        if not state["is_relevant"]:
            # Retries exhausted, but an earlier attempt found something
            # worth trying — a false-negative relevance verdict is a more
            # forgivable failure than throwing away a real find, so give
            # the grounded answer a real shot at it rather than jumping
            # straight to "please clarify".
            documents = state["best_documents"]
            context = state["best_context"]
        else:
            documents = state["documents"]
            # Reuse the context _evaluate already built for this same
            # documents list rather than rebuilding it — evaluate always
            # runs immediately before generation on every path.
            context = state["prompt_context"]

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
        return {
            "generation_mode": "answer",
            "generation_context": context,
            "citations": citations,
            "is_comparison": state.get("is_comparison", False),
        }

    async def _prepare_generation(self, state: RAGState) -> dict:
        return self._decide_generation(state)

    async def _generate_answer(self, state: RAGState) -> dict:
        decision = self._decide_generation(state)
        step = self._step("compose", "Composing the answer")
        reasoning_steps = state["reasoning_steps"] + [step]

        if decision["generation_mode"] == "clarification":
            try:
                answer = await self.llm.generate_clarification(
                    state["question"], state["previous_queries"]
                )
            except Exception:
                logger.warning("Clarification generation failed; using fallback", exc_info=True)
                answer = ""
            answer = answer or _FALLBACK_CLARIFICATION_REPLY
            logger.info(
                "[generate_answer] no relevant content found, returning clarification, total_attempts=%d",
                state["retrieval_attempts"],
            )
            return {"answer": answer, "citations": [], "reasoning_steps": reasoning_steps}

        if decision["is_comparison"]:
            answer = await self.llm.generate_comparison_answer(
                question=state["question"], context=decision["generation_context"]
            )
        else:
            answer = await self.llm.generate_answer(
                question=state["question"], context=decision["generation_context"]
            )
        citations = decision["citations"]
        logger.info(
            "[generate_answer] %d citation(s), answer_chars=%d, total_attempts=%d",
            len(citations),
            len(answer),
            state["retrieval_attempts"],
        )
        return {"answer": answer, "citations": citations, "reasoning_steps": reasoning_steps}

    # --- helpers -----------------------------------------------------------

    async def _llm_rewrite_query(self, original_question: str, previous_queries: list[str]) -> str:
        # Ask Azure OpenAI for a search query genuinely different from
        # every attempt so far — not just the last one. Without the full
        # history, a rewrite has no memory of what it already tried and
        # can end up circling similar phrasings across retries instead of
        # actually broadening coverage.
        #
        # Graph's Search API does exact-ish keyword matching, not fuzzy
        # matching — a single misspelled proper noun (e.g. "Neilstown"
        # instead of "Neillstown") is enough to return zero results for
        # an otherwise-correct query, even though a document with that
        # exact name exists. Left to a generic "try a synonym or broader
        # phrasing" instruction, the LLM doesn't reliably think to check
        # for a typo first, so the strategy below is spelled out and
        # staged by how many attempts have already failed: check spelling
        # first (cheapest, most likely fix for a proper noun typo), then
        # fall back to dropping the most specific/unusual word entirely
        # once spelling alone hasn't produced a new result.
        tried = "\n".join(f'- "{q}"' for q in previous_queries)
        prompt_context = (
            f'None of these searches found a relevant result for the '
            f'question "{original_question}":\n{tried}\n\n'
            "Suggest one new search query, choosing a strategy based on "
            "what hasn't been tried yet in the list above:\n"
            "1. First, check every word for a possible spelling mistake "
            "or typo — especially proper nouns like place, site, or "
            "document names — and correct it while keeping the rest of "
            "the query the same. This is often the actual reason a "
            "search returns nothing: the document exists, but the exact "
            "word searched for is spelled slightly differently.\n"
            "2. If a spelling-corrected version has already been tried "
            "and still found nothing, drop the most specific or unusual "
            "word entirely (often the proper noun that might still be "
            "wrong or too narrow) and search on the more generic "
            "remaining terms instead.\n"
            "3. Only after both of those, fall back to a broader or "
            "narrower phrasing or a synonym for a term that may not "
            "match the document's exact wording.\n"
            "Respond with just the query, no explanation."
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
            "best_documents": [],
            "best_context": "",
            "answer": "",
            "citations": [],
            "reasoning_steps": [],
            "generation_mode": "",
            "generation_context": "",
            "is_comparison": False,
            "entities": [],
            "entity_documents": {},
            "entity_found": {},
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
            reasoning_steps=[ReasoningStep(**s) for s in final_state["reasoning_steps"]],
        )

    async def stream_answer(self, user: UserContext, question: str) -> AsyncIterator[dict]:
        """Same pipeline as answer_question, but yields events as they
        happen instead of returning one ChatResponse at the end:
        {"type": "step", "step": {...}} as each pipeline stage completes,
        {"type": "token", "text": "..."} for each answer token, and a
        final {"type": "done", "answer": ..., "citations": [...],
        "retrieval_attempts": ...}.

        Runs self.graph_stream (identical routing to self.graph, but ends
        right before the final LLM call — see _prepare_generation /
        _prepare_conversational) so the actual generation can be streamed
        here instead of awaited whole inside a graph node.
        """
        logger.info("=== LangGraph stream start: user=%s question=%r ===", user.upn, question)
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
            "best_documents": [],
            "best_context": "",
            "answer": "",
            "citations": [],
            "reasoning_steps": [],
            "generation_mode": "",
            "generation_context": "",
            "is_comparison": False,
            "entities": [],
            "entity_documents": {},
            "entity_found": {},
        }

        final_state = initial_state
        emitted = 0
        async for state in self.graph_stream.astream(
            initial_state, config={"recursion_limit": _RECURSION_LIMIT}, stream_mode="values"
        ):
            final_state = state
            steps = state.get("reasoning_steps", [])
            for step in steps[emitted:]:
                yield {"type": "step", "step": step}
            emitted = len(steps)

        compose_step = self._step("compose", "Composing the answer")
        yield {"type": "step", "step": compose_step}

        mode = final_state.get("generation_mode")
        full_answer = ""
        if mode == "conversational":
            try:
                async for delta in self.llm.generate_conversational_reply_stream(question):
                    full_answer += delta
                    yield {"type": "token", "text": delta}
            except Exception:
                logger.warning("Conversational reply streaming failed; using fallback", exc_info=True)
                full_answer = _FALLBACK_CHITCHAT_REPLY
                yield {"type": "token", "text": full_answer}
            if not full_answer:
                full_answer = _FALLBACK_CHITCHAT_REPLY
                yield {"type": "token", "text": full_answer}
            citations: list[Citation] = []
        elif mode == "clarification":
            try:
                async for delta in self.llm.generate_clarification_stream(
                    question, final_state["previous_queries"]
                ):
                    full_answer += delta
                    yield {"type": "token", "text": delta}
            except Exception:
                logger.warning("Clarification streaming failed; using fallback", exc_info=True)
            if not full_answer:
                full_answer = _FALLBACK_CLARIFICATION_REPLY
                yield {"type": "token", "text": full_answer}
            citations = []
        else:
            context = final_state.get("generation_context", "")
            stream = (
                self.llm.generate_comparison_answer_stream(question, context)
                if final_state.get("is_comparison")
                else self.llm.generate_answer_stream(question, context)
            )
            async for delta in stream:
                full_answer += delta
                yield {"type": "token", "text": delta}
            citations = final_state.get("citations", [])

        logger.info(
            "=== LangGraph stream end: attempts=%d citations=%d ===",
            final_state["retrieval_attempts"],
            len(citations),
        )
        yield {
            "type": "done",
            "answer": full_answer,
            "citations": [c.model_dump() for c in citations],
            "retrieval_attempts": final_state["retrieval_attempts"],
        }
