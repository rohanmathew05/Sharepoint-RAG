"""Verifies the LangGraph V2 pipeline still respects permission boundaries
even though it retries with a rewritten query, and that it actually
retries when the first search comes back empty."""
import pytest

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
