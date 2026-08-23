"""Verifies the LangGraph V2 pipeline's own logic — intent classification,
retry/rewrite mechanics, and permission-token passthrough — with the
SharePoint/Azure OpenAI calls mocked out. Permission enforcement itself
is Microsoft Graph's job (see backend/tests/test_graph_service.py for
proof the delegated token is passed straight through); there is no
application-level ACL logic left in this codebase to test."""
import pytest

from backend.models.auth import UserContext
from backend.services.azure_openai import EntityExtraction
from backend.services.langgraph_pipeline import LangGraphRAGService, _is_chitchat

USER_A = UserContext(
    oid="00000000-0000-0000-0000-0000000000a1",
    upn="user.a@contoso.com",
    name="User A",
    tenant_id="test-tenant",
)


@pytest.mark.parametrize(
    "message", ["hello", "Hi", "hi!", "  hey  ", "thanks", "Thank you", "ok", "test"]
)
def test_chitchat_detection(message):
    assert _is_chitchat(message)


@pytest.mark.parametrize(
    "message",
    [
        "What PPE is required for confined space work?",
        "hi-vis vest requirements",  # contains "hi" but isn't a greeting
        "how many sites are in the UE PCV Survey folder",
    ],
)
def test_real_questions_are_not_chitchat(message):
    assert not _is_chitchat(message)


@pytest.mark.asyncio
async def test_llm_says_chitchat_skips_search_entirely(monkeypatch):
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return False  # LLM verdict: CHITCHAT

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("search should not be reached when the LLM says chitchat")

    async def fake_conversational_reply(question: str) -> str:
        return "Hey there! Ask me anything about the SharePoint docs."

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fail_if_called)
    monkeypatch.setattr(service.llm, "generate_conversational_reply", fake_conversational_reply)

    response = await service.answer_question(USER_A, "anything at all")
    assert response.citations == []
    assert response.retrieval_attempts == 0
    assert response.answer == "Hey there! Ask me anything about the SharePoint docs."


@pytest.mark.asyncio
async def test_llm_says_search_triggers_retrieval(monkeypatch):
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return True  # LLM verdict: SEARCH

    async def fake_search(user, query, max_results=8):
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_clarification(question, attempted_queries):
        return "I couldn't find that — could you give me a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    response = await service.answer_question(USER_A, "what are the coordinates")
    assert response.retrieval_attempts >= 1


@pytest.mark.asyncio
async def test_classification_failure_falls_back_to_heuristic(monkeypatch):
    service = LangGraphRAGService()

    async def broken_classify(question: str) -> bool:
        raise RuntimeError("Azure OpenAI had a bad day")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("search should not be reached for an obvious greeting")

    async def fake_conversational_reply(question: str) -> str:
        return "Hi there!"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", broken_classify)
    monkeypatch.setattr(service.sharepoint, "search", fail_if_called)
    monkeypatch.setattr(service.llm, "generate_conversational_reply", fake_conversational_reply)

    # A genuine greeting should still be caught by the heuristic fallback
    # even though the classifier call itself failed.
    response = await service.answer_question(USER_A, "hello")
    assert response.citations == []
    assert response.retrieval_attempts == 0


@pytest.mark.asyncio
async def test_classification_failure_on_real_question_still_searches(monkeypatch):
    service = LangGraphRAGService()

    async def broken_classify(question: str) -> bool:
        raise RuntimeError("Azure OpenAI had a bad day")

    async def fake_search(user, query, max_results=8):
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_clarification(question, attempted_queries):
        return "I couldn't find that — could you give me a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", broken_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    # Not a greeting, so the heuristic fallback should still trigger a
    # search rather than silently skipping a real question.
    response = await service.answer_question(USER_A, "what are the coordinates")
    assert response.retrieval_attempts >= 1


@pytest.mark.asyncio
async def test_empty_first_search_triggers_rewrite_and_retry(monkeypatch):
    """Exercises the retry loop itself: first search comes back empty,
    the query gets rewritten, the second search finds something."""
    service = LangGraphRAGService()
    search_calls: list[str] = []

    from backend.models.documents import SourceDocument

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        if len(search_calls) == 1:
            return []
        return [
            SourceDocument(
                document_id="doc-1",
                document_name="Pump Specifications.pdf",
                web_url="https://contoso.sharepoint.com/pump-specs.pdf",
                relevant_content="Model P-450 centrifugal pump specs.",
            )
        ]

    async def fake_generate_answer(question, context):
        return "Based on the documents: Model P-450."

    async def fake_rewrite(original_question, previous_queries):
        return "pump specifications"

    async def fake_evaluate_relevance(question, context):
        return bool(context.strip())

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)

    response = await service.answer_question(USER_A, "what's the pump spec sheet say")

    assert len(search_calls) == 2
    assert response.retrieval_attempts == 2
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "Pump Specifications.pdf"


@pytest.mark.asyncio
async def test_llm_relevance_check_triggers_retry_on_unhelpful_snippet(monkeypatch):
    """The exact scenario an len(documents) > 0 presence check misses:
    search finds the right document, but the snippet doesn't actually
    contain the specific fact asked for. A real LLM relevance judgment
    (not just "did we get any documents back") is what catches this."""
    service = LangGraphRAGService()
    search_calls: list[str] = []

    from backend.models.documents import SourceDocument

    unhelpful_doc = SourceDocument(
        document_id="doc-1",
        document_name="WFV0002188 TULLYLOST PRV.xlsx",
        web_url="https://contoso.sharepoint.com/tullylost-prv.xlsx",
        relevant_content="Site Name TULLYLOST PRV, Road Reference L7002, confined space: yes.",
    )

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        return [unhelpful_doc]  # same doc found both times

    # First call: snippet doesn't mention the GIS ID -> NOT_RELEVANT.
    # Second call (after rewrite): pretend the rewritten query surfaced
    # a snippet that does -> RELEVANT.
    async def fake_evaluate_relevance(question, context):
        return len(search_calls) > 1

    async def fake_generate_answer(question, context):
        return "The GIS ID reference is WFV0002188."

    async def fake_rewrite(original_question, previous_queries):
        return "GIS ID reference Tullylost"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)

    response = await service.answer_question(USER_A, "what is the GIS ID reference for tullylost prv?")

    assert len(search_calls) == 2  # retried despite finding a document on attempt 1
    assert response.retrieval_attempts == 2
    assert "WFV0002188" in response.answer


@pytest.mark.asyncio
async def test_retries_are_capped_by_max_retries(monkeypatch):
    service = LangGraphRAGService()
    search_calls: list[str] = []

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        return []  # never finds anything

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_rewrite(original_question, previous_queries):
        return f"{previous_queries[-1]} broader"

    async def fake_clarification(question, attempted_queries):
        return "I couldn't find that — could you give me a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    response = await service.answer_question(USER_A, "something nobody has")

    from backend.services.langgraph_pipeline import MAX_RETRIES

    assert len(search_calls) == MAX_RETRIES
    assert response.citations == []
    # Each retry actually used a different query, not the same one
    # repeated MAX_RETRIES times.
    assert len(set(search_calls)) == MAX_RETRIES


@pytest.mark.asyncio
async def test_exhausted_retries_use_llm_generated_clarification(monkeypatch):
    """Once every retry is exhausted without a relevant result, the final
    answer should be whatever the clarification LLM call returns — not a
    hardcoded string, and not the raw ungrounded generate_answer output
    that reads like a broken error message."""
    service = LangGraphRAGService()
    captured_attempts: list[list[str]] = []

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        return []  # never finds anything

    async def fake_rewrite(original_question, previous_queries):
        return f"{previous_queries[-1]} broader"

    async def fake_clarification(question, attempted_queries):
        captured_attempts.append(list(attempted_queries))
        return "I couldn't find a match — could you share the exact site name or a reference number?"

    async def fail_if_called(question, context):
        raise AssertionError("generate_answer should not be used once retries are exhausted")

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)
    monkeypatch.setattr(service.llm, "generate_answer", fail_if_called)

    response = await service.answer_question(USER_A, "what is the wfv number for tullylost")

    assert response.answer == (
        "I couldn't find a match — could you share the exact site name or a reference number?"
    )
    assert response.citations == []
    assert len(captured_attempts) == 1
    assert len(captured_attempts[0]) > 0  # full query history was passed through


@pytest.mark.asyncio
async def test_exhausted_retries_fall_back_to_best_attempt_content(monkeypatch):
    """Reproduces the real failure this fixes: an early attempt finds the
    right document but gets marked not-relevant, a later rewrite finds
    nothing at all, and retries run out. The pipeline should still try to
    answer from the best (richest) content ever found rather than
    discarding it and asking the user for more detail as if nothing had
    ever turned up."""
    service = LangGraphRAGService()

    from backend.models.documents import SourceDocument

    good_doc = SourceDocument(
        document_id="doc-1",
        document_name="NEILLSTOWN COMMUNITY CENTRE.xlsx",
        web_url="https://contoso.sharepoint.com/neillstown.xlsx",
        relevant_content="Site Name NEILLSTOWN COMMUNITY CENTRE, GIS ID NC-4471.",
    )

    search_calls: list[str] = []

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        if len(search_calls) == 1:
            return [good_doc]  # found the right thing...
        return []  # ...but every later rewrite finds nothing

    async def fake_evaluate_relevance(question, context):
        return False  # ...and gets marked not-relevant every time

    async def fake_rewrite(original_question, previous_queries):
        return f"{previous_queries[-1]} broader"

    async def fake_generate_answer(question, context):
        assert "NC-4471" in context  # must be answering from the best-found context
        return "The GIS ID is NC-4471."

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("should try the best-found content, not ask for clarification")

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fail_if_called)

    response = await service.answer_question(USER_A, "what is the GIS ID for neillstown community centre")

    assert response.answer == "The GIS ID is NC-4471."
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "NEILLSTOWN COMMUNITY CENTRE.xlsx"


@pytest.mark.asyncio
async def test_chitchat_reply_is_llm_generated(monkeypatch):
    """The greeting/chitchat response should come from a genuine LLM
    call, not a hardcoded canned string, so it actually reflects what
    the user said."""
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return False  # LLM verdict: CHITCHAT

    async def fake_conversational_reply(question: str) -> str:
        assert question == "good morning!"
        return "Good morning! Happy to help you find anything in the SharePoint docs."

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "generate_conversational_reply", fake_conversational_reply)

    response = await service.answer_question(USER_A, "good morning!")

    assert response.answer == "Good morning! Happy to help you find anything in the SharePoint docs."
    assert response.citations == []


@pytest.mark.asyncio
async def test_rewrite_prompt_includes_full_query_history(monkeypatch):
    """_llm_rewrite_query should tell the LLM everything already tried,
    not just the most recent query, so retries don't circle back to
    similar phrasings."""
    service = LangGraphRAGService()
    captured_prompt = {}

    async def fake_generate_answer(question, context):
        captured_prompt["question"] = question
        return "a genuinely new query"

    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)

    result = await service._llm_rewrite_query(
        "what is the GIS ID for tullylost prv",
        ["tullylost prv", "GIS ID tullylost", "facility reference tullylost"],
    )

    assert result == "a genuinely new query"
    prompt = captured_prompt["question"]
    assert "tullylost prv" in prompt
    assert "GIS ID tullylost" in prompt
    assert "facility reference tullylost" in prompt


@pytest.mark.asyncio
async def test_rewrite_prompt_prioritizes_spelling_correction_before_dropping_words(monkeypatch):
    """A single misspelled proper noun (e.g. "Neilstown" for the real
    "Neillstown") is enough for Graph's keyword search to return zero
    results even though the right document exists. The rewrite prompt
    should explicitly tell the LLM to check for a typo first, before
    falling back to dropping words entirely."""
    service = LangGraphRAGService()
    captured_prompt = {}

    async def fake_generate_answer(question, context):
        captured_prompt["question"] = question
        return "Neillstown Community Centre"

    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)

    await service._llm_rewrite_query(
        "what is the GIS ID for neilstown community centre",
        ["neilstown community centre"],
    )

    prompt = captured_prompt["question"]
    assert "spelling" in prompt.lower() or "typo" in prompt.lower()
    assert "drop" in prompt.lower()


@pytest.mark.asyncio
async def test_delegated_token_search_is_the_only_permission_boundary(monkeypatch):
    """The pipeline itself does no filtering — SharePointService.search()
    is called with the user object as-is, and Microsoft Graph (via the
    OBO-derived token) is what decides what comes back. This just proves
    the pipeline passes the real user through unmodified."""
    service = LangGraphRAGService()
    received_users = []

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_search(user, query, max_results=8):
        received_users.append(user)
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_clarification(question, attempted_queries):
        return "I couldn't find that — could you give me a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    await service.answer_question(USER_A, "what are the coordinates")

    assert len(received_users) >= 1
    assert all(u is USER_A for u in received_users)


# --- comparison ("compare X and Y") handling ---------------------------


@pytest.mark.asyncio
async def test_single_topic_question_never_calls_entity_classification(monkeypatch):
    """The cheap string pre-filter should keep classify_entities from
    ever being called on an ordinary single-topic question — no added
    LLM call, no regression in cost/latency for the common case."""
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return True

    async def fail_if_called(question: str):
        raise AssertionError("classify_entities should not be called for a non-comparison question")

    async def fake_search(user, query, max_results=8):
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_clarification(question, attempted_queries):
        return "Could you share a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", fail_if_called)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    response = await service.answer_question(USER_A, "What PPE is required for confined space work?")
    assert response.retrieval_attempts >= 1


@pytest.mark.asyncio
async def test_comparison_question_searches_each_entity_and_merges_results(monkeypatch):
    """Reproduces the reported bug: "compare neilstown and ronanstown"
    are two separate documents that a single blended search often can't
    surface together. Each entity should get its own search, and both
    documents should end up in the merged context/citations."""
    service = LangGraphRAGService()

    from backend.models.documents import SourceDocument

    neilstown_doc = SourceDocument(
        document_id="doc-neilstown",
        document_name="NEILSTOWN.xlsx",
        web_url="https://contoso.sharepoint.com/neilstown.xlsx",
        relevant_content="Site Name NEILSTOWN, GIS ID N-1.",
    )
    ronanstown_doc = SourceDocument(
        document_id="doc-ronanstown",
        document_name="RONANSTOWN.xlsx",
        web_url="https://contoso.sharepoint.com/ronanstown.xlsx",
        relevant_content="Site Name RONANSTOWN, GIS ID R-2.",
    )

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_classify_entities(question: str) -> EntityExtraction:
        return EntityExtraction(is_comparison=True, entities=["neilstown", "ronanstown"])

    search_calls: list[str] = []

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        if "neilstown" in query.lower():
            return [neilstown_doc]
        if "ronanstown" in query.lower():
            return [ronanstown_doc]
        return []

    async def fake_evaluate_relevance(question, context):
        return bool(context.strip())

    async def fake_comparison_answer(question, context):
        assert "neilstown" in context.lower() and "ronanstown" in context.lower()
        return "Neilstown is N-1 and Ronanstown is R-2."

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("the single-topic generate_answer should not be used for a comparison")

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", fake_classify_entities)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service.llm, "generate_comparison_answer", fake_comparison_answer)
    monkeypatch.setattr(service.llm, "generate_answer", fail_if_called)

    response = await service.answer_question(USER_A, "compare neilstown and ronanstown")

    assert search_calls == ["neilstown", "ronanstown"]
    assert response.answer == "Neilstown is N-1 and Ronanstown is R-2."
    document_names = {c.document_name for c in response.citations}
    assert document_names == {"NEILSTOWN.xlsx", "RONANSTOWN.xlsx"}


@pytest.mark.asyncio
async def test_comparison_with_one_entity_not_found_still_answers_for_the_other(monkeypatch):
    """If a search for one entity comes back empty while another
    succeeds, that entity should not be silently dropped — the merged
    context should explicitly note nothing was found for it, and the
    other entity's result should still make it through to the answer."""
    service = LangGraphRAGService()

    from backend.models.documents import SourceDocument

    ronanstown_doc = SourceDocument(
        document_id="doc-ronanstown",
        document_name="RONANSTOWN.xlsx",
        web_url="https://contoso.sharepoint.com/ronanstown.xlsx",
        relevant_content="Site Name RONANSTOWN, GIS ID R-2.",
    )

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_classify_entities(question: str) -> EntityExtraction:
        return EntityExtraction(is_comparison=True, entities=["cliffield", "ronanstown"])

    async def fake_search(user, query, max_results=8):
        if "ronanstown" in query.lower():
            return [ronanstown_doc]
        return []  # cliffield is never found, even after a rewrite

    async def fake_evaluate_relevance(question, context):
        return bool(context.strip())

    async def fake_rewrite(original_question, previous_queries):
        return f"{previous_queries[-1]} site"

    captured_context = {}

    async def fake_comparison_answer(question, context):
        captured_context["context"] = context
        return "I found information on ronanstown but nothing on cliffield."

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", fake_classify_entities)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)
    monkeypatch.setattr(service.llm, "generate_comparison_answer", fake_comparison_answer)

    response = await service.answer_question(USER_A, "compare cliffield and ronanstown")

    assert 'No documents found for "cliffield"' in captured_context["context"]
    assert "RONANSTOWN" in captured_context["context"]
    assert len(response.citations) == 1
    assert response.citations[0].document_name == "RONANSTOWN.xlsx"


@pytest.mark.asyncio
async def test_three_entity_comparison_generalizes(monkeypatch):
    """The comparison path shouldn't hardcode two entities — three (or
    more) named things should each get their own search and section."""
    service = LangGraphRAGService()

    from backend.models.documents import SourceDocument

    docs = {
        "neilstown": SourceDocument(
            document_id="doc-1", document_name="NEILSTOWN.xlsx",
            web_url="https://contoso.sharepoint.com/n.xlsx", relevant_content="N info",
        ),
        "ronanstown": SourceDocument(
            document_id="doc-2", document_name="RONANSTOWN.xlsx",
            web_url="https://contoso.sharepoint.com/r.xlsx", relevant_content="R info",
        ),
        "cliffield": SourceDocument(
            document_id="doc-3", document_name="CLIFFIELD.xlsx",
            web_url="https://contoso.sharepoint.com/c.xlsx", relevant_content="C info",
        ),
    }

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_classify_entities(question: str) -> EntityExtraction:
        return EntityExtraction(is_comparison=True, entities=["neilstown", "ronanstown", "cliffield"])

    search_calls: list[str] = []

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        return [docs[query.lower()]] if query.lower() in docs else []

    async def fake_evaluate_relevance(question, context):
        return bool(context.strip())

    async def fake_comparison_answer(question, context):
        return "compared all three"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", fake_classify_entities)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service.llm, "generate_comparison_answer", fake_comparison_answer)

    response = await service.answer_question(USER_A, "compare neilstown, ronanstown and cliffield")

    assert set(search_calls) == {"neilstown", "ronanstown", "cliffield"}
    assert len(response.citations) == 3


@pytest.mark.asyncio
async def test_entity_classification_failure_falls_back_to_single_search(monkeypatch):
    """A classify_entities hiccup should regress to today's single-search
    behavior, never break the pipeline."""
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return True

    async def broken_classify_entities(question: str):
        raise RuntimeError("Azure OpenAI had a bad day")

    async def fake_search(user, query, max_results=8):
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    async def fake_clarification(question, attempted_queries):
        return "Could you share a document name or reference number?"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", broken_classify_entities)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service.llm, "generate_clarification", fake_clarification)

    response = await service.answer_question(USER_A, "compare neilstown and ronanstown")
    assert response.retrieval_attempts >= 1


@pytest.mark.asyncio
async def test_comparison_entity_retries_and_recovers_from_a_spelling_mistake(monkeypatch):
    """Reproduces the real failure: "Neillstown Community Center" (the
    user's spelling) finds nothing because the actual document says
    "Centre". The per-entity retry loop should get more than one shot at
    this (not just a single rewrite attempt), and each attempt should
    show up as its own reasoning step so a retry is actually visible
    instead of looking like nothing happened."""
    service = LangGraphRAGService()

    from backend.models.documents import SourceDocument

    centre_doc = SourceDocument(
        document_id="doc-neillstown",
        document_name="NEILLSTOWN COMMUNITY CENTRE.xlsx",
        web_url="https://contoso.sharepoint.com/neillstown-centre.xlsx",
        relevant_content="Site Name NEILLSTOWN COMMUNITY CENTRE, GIS ID NC-4471.",
    )
    ronanstown_doc = SourceDocument(
        document_id="doc-ronanstown",
        document_name="RONANSTOWN.xlsx",
        web_url="https://contoso.sharepoint.com/ronanstown.xlsx",
        relevant_content="Site Name RONANSTOWN, GIS ID R-2.",
    )

    async def fake_classify(question: str) -> bool:
        return True

    async def fake_classify_entities(question: str) -> EntityExtraction:
        return EntityExtraction(
            is_comparison=True, entities=["Neillstown Community Center", "ronanstown"]
        )

    search_calls: list[str] = []

    async def fake_search(user, query, max_results=8):
        search_calls.append(query)
        if "centre" in query.lower():
            return [centre_doc]
        if "ronanstown" in query.lower():
            return [ronanstown_doc]
        return []  # "Center" (wrong spelling) never matches

    async def fake_evaluate_relevance(question, context):
        return bool(context.strip())

    async def fake_rewrite(original_question, previous_queries):
        # Simulates the real spelling-correction-first rewrite strategy.
        return original_question.replace("Center", "Centre")

    async def fake_comparison_answer(question, context):
        return "Neillstown Community Centre is NC-4471 and Ronanstown is R-2."

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.llm, "classify_entities", fake_classify_entities)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "evaluate_relevance", fake_evaluate_relevance)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)
    monkeypatch.setattr(service.llm, "generate_comparison_answer", fake_comparison_answer)

    response = await service.answer_question(
        USER_A, "compare Neillstown Community Center and ronanstown"
    )

    # The first attempt (wrong spelling) failed, and a second attempt
    # (after rewrite) found the document — more than one search call for
    # that entity, not just the single initial attempt.
    assert "Neillstown Community Center" in search_calls
    assert "Neillstown Community Centre" in search_calls
    assert len(response.citations) == 2
    document_names = {c.document_name for c in response.citations}
    assert document_names == {"NEILLSTOWN COMMUNITY CENTRE.xlsx", "RONANSTOWN.xlsx"}

    # Both attempts for the mis-spelled entity should be visible as
    # separate reasoning steps, not collapsed into one final verdict.
    search_step_labels = [
        s.label for s in response.reasoning_steps if s.kind == "search"
    ]
    assert 'Searching for "Neillstown Community Center"' in search_step_labels
    assert 'Searching for "Neillstown Community Centre"' in search_step_labels
