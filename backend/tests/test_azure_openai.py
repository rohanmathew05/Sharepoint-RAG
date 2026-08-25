"""Unit tests for AzureOpenAIService against a mocked Azure client — no
real Azure OpenAI credentials or network access needed. This is the only
path now that DEMO_MODE has been removed."""
from types import SimpleNamespace

import pytest

from backend.models.chat import ChatMessage
from backend.services.azure_openai import (
    SYSTEM_PROMPT,
    AzureOpenAIService,
    IntentClassification,
    QueryContextualization,
    RelevanceEvaluation,
)


class FakeAzureClient:
    def __init__(
        self,
        chat_content: str = "answer",
        embedding: list[float] | None = None,
        parsed=None,
    ):
        self.last_chat_kwargs: dict | None = None
        self.last_parse_kwargs: dict | None = None
        self._chat_content = chat_content
        self._embedding = embedding or [0.1, 0.2, 0.3]
        self._parsed = parsed
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.embeddings = SimpleNamespace(create=self._create_embedding)
        self.beta = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(parse=self._parse_chat))
        )

    async def _create_chat(self, **kwargs):
        self.last_chat_kwargs = kwargs
        message = SimpleNamespace(content=self._chat_content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def _create_embedding(self, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=self._embedding)])

    async def _parse_chat(self, **kwargs):
        self.last_parse_kwargs = kwargs
        message = SimpleNamespace(parsed=self._parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


@pytest.mark.asyncio
async def test_generate_answer_grounds_in_context_via_system_prompt(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="Wear a full-body harness.")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    answer = await service.generate_answer(
        question="What PPE is required?",
        context="[Confined Space Policy.pdf]\nWorkers must wear a harness.",
    )

    assert answer == "Wear a full-body harness."
    messages = fake_client.last_chat_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert "Workers must wear a harness" in messages[1]["content"]
    assert "What PPE is required?" in messages[1]["content"]


@pytest.mark.asyncio
async def test_generate_answer_threads_history_between_system_and_final_user_turn(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="An answer.")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    history = [
        ChatMessage(role="user", content="what is the deadline for site A?"),
        ChatMessage(role="assistant", content="The deadline for site A is June 1st."),
    ]
    await service.generate_answer(question="what about site B?", context="", history=history)

    messages = fake_client.last_chat_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[1] == {"role": "user", "content": "what is the deadline for site A?"}
    assert messages[2] == {"role": "assistant", "content": "The deadline for site A is June 1st."}
    assert "what about site B?" in messages[3]["content"]


@pytest.mark.asyncio
async def test_generate_answer_with_no_history_omits_history_turns(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="An answer.")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    await service.generate_answer(question="hi", context="")

    messages = fake_client.last_chat_kwargs["messages"]
    assert len(messages) == 2  # just system + the final user turn, no gap


@pytest.mark.asyncio
async def test_generate_answer_handles_empty_content_response(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content=None)
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    answer = await service.generate_answer(question="hi", context="")
    assert answer == ""


@pytest.mark.asyncio
async def test_embed_returns_the_embedding_vector(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(embedding=[0.5, 0.6, 0.7])
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    vector = await service.embed("some text")
    assert vector == [0.5, 0.6, 0.7]


@pytest.mark.asyncio
async def test_classify_needs_retrieval_true_for_search_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=IntentClassification(needs_retrieval=True))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    assert await service.classify_needs_retrieval("What PPE is required?") is True
    assert fake_client.last_parse_kwargs["temperature"] == 0
    assert fake_client.last_parse_kwargs["response_format"] is IntentClassification


@pytest.mark.asyncio
async def test_classify_needs_retrieval_false_for_chitchat_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=IntentClassification(needs_retrieval=False))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    assert await service.classify_needs_retrieval("hello") is False


@pytest.mark.asyncio
async def test_evaluate_relevance_skips_api_call_for_empty_context(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=RelevanceEvaluation(is_relevant=True))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("question", "")
    assert result is False
    assert fake_client.last_parse_kwargs is None  # never called the API


@pytest.mark.asyncio
async def test_evaluate_relevance_true_for_relevant_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=RelevanceEvaluation(is_relevant=True))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("What is the GIS ID?", "[doc] some excerpt")
    assert result is True
    assert fake_client.last_parse_kwargs["response_format"] is RelevanceEvaluation


@pytest.mark.asyncio
async def test_evaluate_relevance_false_for_not_relevant_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=RelevanceEvaluation(is_relevant=False))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("What is the GIS ID?", "[doc] unrelated excerpt")
    assert result is False


@pytest.mark.asyncio
async def test_generate_conversational_reply_calls_the_llm(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="Hey! Ask me about the SharePoint docs anytime.")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    reply = await service.generate_conversational_reply("good morning!")

    assert reply == "Hey! Ask me about the SharePoint docs anytime."
    messages = fake_client.last_chat_kwargs["messages"]
    assert messages[1] == {"role": "user", "content": "good morning!"}


@pytest.mark.asyncio
async def test_contextualize_query_skips_api_call_with_no_history(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(
        parsed=QueryContextualization(standalone_query="should never be used")
    )
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.contextualize_query("could you find more details")

    assert result == "could you find more details"
    assert fake_client.last_parse_kwargs is None  # never called the API


@pytest.mark.asyncio
async def test_contextualize_query_resolves_a_vague_follow_up_using_history(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(
        parsed=QueryContextualization(standalone_query="Neilstown Ronanstown details")
    )
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    history = [
        ChatMessage(role="user", content="compare neilstown and ronanstown for me"),
        ChatMessage(role="assistant", content="Neilstown scored 61.78, Ronanstown 61.22..."),
    ]
    result = await service.contextualize_query("could you find more details", history=history)

    assert result == "Neilstown Ronanstown details"
    messages = fake_client.last_parse_kwargs["messages"]
    assert messages[1] == {"role": "user", "content": "compare neilstown and ronanstown for me"}
    assert messages[-1] == {"role": "user", "content": "could you find more details"}
    assert fake_client.last_parse_kwargs["response_format"] is QueryContextualization


@pytest.mark.asyncio
async def test_generate_clarification_includes_attempted_queries(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(
        chat_content="I couldn't find that — could you share a reference number?"
    )
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    reply = await service.generate_clarification(
        "what is the wfv number for tullylost",
        ["tullylost", "wfv number tullylost"],
    )

    assert reply == "I couldn't find that — could you share a reference number?"
    user_content = fake_client.last_chat_kwargs["messages"][1]["content"]
    assert "tullylost" in user_content
    assert "wfv number tullylost" in user_content
