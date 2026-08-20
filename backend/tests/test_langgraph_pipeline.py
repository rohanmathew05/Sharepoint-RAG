"""Verifies the LangGraph V2 pipeline still respects permission boundaries
even though it retries with a rewritten query, and that it actually
retries when the first search comes back empty."""
import pytest

from backend.core.config import get_settings
from backend.models.auth import UserContext
from backend.services.langgraph_pipeline import LangGraphRAGService, _is_chitchat

USER_A = UserContext(
    oid="00000000-0000-0000-0000-0000000000a1",
    upn="user.a@contoso.com",
    name="User A",
    tenant_id="demo-tenant",
)
USER_B = UserContext(
    oid="00000000-0000-0000-0000-0000000000b1",
    upn="user.b@contoso.com",
    name="User B",
    tenant_id="demo-tenant",
)


@pytest.mark.asyncio
async def test_user_a_gets_no_engineering_citations_even_after_retries():
    service = LangGraphRAGService()
    response = await service.answer_question(USER_A, "What are the pump specifications?")
    assert response.citations == []
    # Should have retried at least once (rewritten query) before giving up.
    assert response.retrieval_attempts >= 2


@pytest.mark.asyncio
async def test_user_b_gets_engineering_citations_on_first_attempt():
    service = LangGraphRAGService()
    response = await service.answer_question(USER_B, "What are the pump specifications?")
    names = {c.document_name for c in response.citations}
    assert "Pump Specifications.pdf" in names
    assert response.retrieval_attempts == 1


@pytest.mark.asyncio
async def test_no_user_ever_gets_hr_citations_via_v2():
    service = LangGraphRAGService()
    for user in (USER_A, USER_B):
        response = await service.answer_question(user, "What are the salary bands and market benchmarks?")
        assert response.citations == []


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
async def test_greeting_skips_search_entirely():
    service = LangGraphRAGService()
    response = await service.answer_question(USER_A, "hello")
    assert response.citations == []
    assert response.retrieval_attempts == 0


@pytest.mark.asyncio
async def test_real_question_still_searches():
    service = LangGraphRAGService()
    response = await service.answer_question(USER_A, "What PPE is required for confined space work?")
    assert response.retrieval_attempts >= 1
    assert len(response.citations) > 0


@pytest.fixture
def real_mode(monkeypatch):
    """These tests exercise the real (non-demo) intent-classification
    path, mocking the LLM/search calls so nothing actually reaches
    Azure OpenAI or Microsoft Graph."""
    settings = get_settings()
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    yield settings


@pytest.mark.asyncio
async def test_real_mode_llm_says_chitchat_skips_search(monkeypatch, real_mode):
    service = LangGraphRAGService()

    async def fake_classify(question: str) -> bool:
        return False  # LLM verdict: CHITCHAT

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("search should not be reached when LLM says chitchat")

    monkeypatch.setattr(service.llm, "classify_needs_retrieval", fake_classify)
    monkeypatch.setattr(service.sharepoint, "search", fail_if_called)

    response = await service.answer_question(USER_A, "anything at all")
    assert response.citations == []
    assert response.retrieval_attempts == 0


@pytest.mark.asyncio
async def test_real_mode_llm_says_search_triggers_retrieval(monkeypatch, real_mode):
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
async def test_real_mode_classification_failure_defaults_to_search(monkeypatch, real_mode):
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

    # Should not raise, and should still have attempted a search rather
    # than silently skipping it.
    response = await service.answer_question(USER_A, "what are the coordinates")
    assert response.retrieval_attempts >= 1
