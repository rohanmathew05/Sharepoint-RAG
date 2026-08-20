"""Unit tests for AzureOpenAIService against a mocked Azure client — no
real Azure OpenAI credentials or network access needed. This is the only
path now that DEMO_MODE has been removed."""
from types import SimpleNamespace

import pytest

from backend.services.azure_openai import SYSTEM_PROMPT, AzureOpenAIService


class FakeAzureClient:
    def __init__(self, chat_content: str = "answer", embedding: list[float] | None = None):
        self.last_chat_kwargs: dict | None = None
        self._chat_content = chat_content
        self._embedding = embedding or [0.1, 0.2, 0.3]
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.embeddings = SimpleNamespace(create=self._create_embedding)

    async def _create_chat(self, **kwargs):
        self.last_chat_kwargs = kwargs
        message = SimpleNamespace(content=self._chat_content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def _create_embedding(self, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(embedding=self._embedding)])


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
    fake_client = FakeAzureClient(chat_content="SEARCH")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    assert await service.classify_needs_retrieval("What PPE is required?") is True
    assert fake_client.last_chat_kwargs["max_tokens"] == 10
    assert fake_client.last_chat_kwargs["temperature"] == 0


@pytest.mark.asyncio
async def test_classify_needs_retrieval_false_for_chitchat_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="CHITCHAT")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    assert await service.classify_needs_retrieval("hello") is False


@pytest.mark.asyncio
async def test_evaluate_relevance_skips_api_call_for_empty_context(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="RELEVANT")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("question", "")
    assert result is False
    assert fake_client.last_chat_kwargs is None  # never called the API


@pytest.mark.asyncio
async def test_evaluate_relevance_true_for_relevant_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="RELEVANT")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("What is the GIS ID?", "[doc] some excerpt")
    assert result is True


@pytest.mark.asyncio
async def test_evaluate_relevance_false_for_not_relevant_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(chat_content="NOT_RELEVANT")
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("What is the GIS ID?", "[doc] unrelated excerpt")
    assert result is False
