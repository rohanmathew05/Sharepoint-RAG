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
