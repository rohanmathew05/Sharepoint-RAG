"""Verifies the LangGraph V2 pipeline's own logic — intent classification,
retry/rewrite mechanics, and permission-token passthrough — with the
SharePoint/Azure OpenAI calls mocked out. Permission enforcement itself
is Microsoft Graph's job (see backend/tests/test_graph_service.py for
proof the delegated token is passed straight through); there is no
application-level ACL logic left in this codebase to test."""
import pytest

from backend.models.auth import UserContext
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

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fail_if_called)

    response = await service.answer_question(USER_A, "anything at all")
    assert response.citations == []
    assert response.retrieval_attempts == 0


@pytest.mark.asyncio
async def test_llm_says_search_triggers_retrieval(monkeypatch):
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return True  # LLM verdict: SEARCH

    async def fake_search(user, query, max_results=8):
        return []

    async def fake_generate_answer(question, context):
        return "no relevant documents found"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)

    response = await service.answer_question(USER_A, "what are the coordinates")
    assert response.retrieval_attempts >= 1


@pytest.mark.asyncio
async def test_classification_failure_falls_back_to_heuristic(monkeypatch):
    service = LangGraphRAGService()

    async def broken_classify(question: str) -> bool:
        raise RuntimeError("Azure OpenAI had a bad day")

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("search should not be reached for an obvious greeting")

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", broken_classify)
    monkeypatch.setattr(service.sharepoint, "search", fail_if_called)

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

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", broken_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)

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

    async def fake_rewrite(original_question, previous_query):
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

    async def fake_rewrite(original_question, previous_query):
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

    async def fake_rewrite(original_question, previous_query):
        return f"{previous_query} broader"

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)
    monkeypatch.setattr(service, "_llm_rewrite_query", fake_rewrite)

    response = await service.answer_question(USER_A, "something nobody has")

    from backend.services.langgraph_pipeline import MAX_RETRIES

    assert len(search_calls) == MAX_RETRIES
    assert response.citations == []


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

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fake_search)
    monkeypatch.setattr(service.llm, "generate_answer", fake_generate_answer)

    await service.answer_question(USER_A, "what are the coordinates")

    assert len(received_users) >= 1
    assert all(u is USER_A for u in received_users)
