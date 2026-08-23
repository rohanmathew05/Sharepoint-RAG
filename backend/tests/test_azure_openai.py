"""Unit tests for AzureOpenAIService against a mocked Azure client — no
real Azure OpenAI credentials or network access needed. This is the only
path now that DEMO_MODE has been removed.

The classification/evaluation methods go through pydantic_ai Agents (see
azure_openai.py), which call the same client.chat.completions.create()
used for plain-text generation, but with a `tools` schema attached and
expect the verdict back as a tool call rather than a `response_format`
parse — so FakeAzureClient simulates that tool-call response shape
whenever a call includes `tools`, using real openai.types.chat objects
since pydantic_ai validates the response type strictly.
"""
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

from backend.services.azure_openai import (
    SYSTEM_PROMPT,
    AzureOpenAIService,
    IntentClassification,
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
        self._chat_content = chat_content
        self._embedding = embedding or [0.1, 0.2, 0.3]
        self._parsed = parsed
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create_chat))
        self.embeddings = SimpleNamespace(create=self._create_embedding)

    async def _create_chat(self, **kwargs):
        self.last_chat_kwargs = kwargs
        tools = kwargs.get("tools")
        if tools:
            tool_name = tools[0]["function"]["name"]
            return ChatCompletion(
                id="chatcmpl-test",
                object="chat.completion",
                created=0,
                model="test-deployment",
                choices=[
                    Choice(
                        index=0,
                        finish_reason="tool_calls",
                        message=ChatCompletionMessage(
                            role="assistant",
                            content=None,
                            tool_calls=[
                                ChatCompletionMessageToolCall(
                                    id="call_1",
                                    type="function",
                                    function=Function(
                                        name=tool_name,
                                        arguments=self._parsed.model_dump_json(),
                                    ),
                                )
                            ],
                        ),
                    )
                ],
            )
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
    fake_client = FakeAzureClient(parsed=IntentClassification(needs_retrieval=True))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    assert await service.classify_needs_retrieval("What PPE is required?") is True
    assert fake_client.last_chat_kwargs["temperature"] == 0
    schema_properties = fake_client.last_chat_kwargs["tools"][0]["function"]["parameters"][
        "properties"
    ]
    assert "needs_retrieval" in schema_properties


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
    assert fake_client.last_chat_kwargs is None  # never called the API


@pytest.mark.asyncio
async def test_evaluate_relevance_true_for_relevant_verdict(monkeypatch):
    service = AzureOpenAIService()
    fake_client = FakeAzureClient(parsed=RelevanceEvaluation(is_relevant=True))
    monkeypatch.setattr(service, "_get_client", lambda: fake_client)

    result = await service.evaluate_relevance("What is the GIS ID?", "[doc] some excerpt")
    assert result is True
    schema_properties = fake_client.last_chat_kwargs["tools"][0]["function"]["parameters"][
        "properties"
    ]
    assert "is_relevant" in schema_properties


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
