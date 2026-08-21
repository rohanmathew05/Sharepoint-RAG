"""Azure OpenAI client wrapper for chat generation and embeddings.

Credentials are read from environment variables server-side only (see
backend/core/config.py) and are never returned to, or reachable from, the
React frontend.
"""
from typing import AsyncIterator

from openai import AsyncAzureOpenAI
from pydantic import BaseModel

from backend.core.config import get_settings

SYSTEM_PROMPT = (
    "You are an internal company AI assistant. Answer the user's question "
    "using ONLY the information in the provided SharePoint document "
    "excerpts below. If the excerpts do not contain enough information to "
    "answer, say so plainly instead of guessing. Do not invent facts, and "
    "do not reference documents that are not listed in the context, even "
    "if you believe they exist."
)

INTENT_CLASSIFIER_SYSTEM_PROMPT = (
    "You decide whether a user's message requires searching internal "
    "company SharePoint documents to answer, or whether it's a greeting, "
    "thanks, or other chitchat that needs no document search."
)

RELEVANCE_EVALUATOR_SYSTEM_PROMPT = (
    "You judge whether the provided SharePoint document excerpts contain "
    "enough information to actually answer the user's question — not "
    "just whether they're on the same general topic. If the excerpts "
    "would let someone give a real, specific answer, the excerpts are "
    "relevant. If they're empty, off-topic, or only tangentially related "
    "and missing the specific information asked for, they are not "
    "relevant."
)

CONVERSATIONAL_SYSTEM_PROMPT = (
    "You are an internal company AI assistant that answers questions about "
    "the company's SharePoint documents. The user just sent a greeting, "
    "thanks, or other message that doesn't need a document search. Reply "
    "briefly and naturally (1-2 sentences), and if it fits the moment, "
    "mention that you can look things up in the company's SharePoint "
    "documents. Sound like a helpful colleague, not a scripted bot."
)

CLARIFICATION_SYSTEM_PROMPT = (
    "A user asked a question about internal company SharePoint documents. "
    "Several different searches were tried and none of them found a "
    "document that actually answers it. Write a brief, natural reply "
    "(2-3 sentences) telling them you couldn't find the answer in the "
    "documents you have access to. Based on the question and the search "
    "attempts already made, suggest what specific detail would help — "
    "e.g. an exact site/document name, a reference number, a date range, "
    "or a different term for what they're describing. Sound like a "
    "helpful colleague, not a robotic error message — do not say things "
    "like 'the provided excerpts do not contain' or 'I cannot assist "
    "with this request'."
)


class IntentClassification(BaseModel):
    needs_retrieval: bool


class RelevanceEvaluation(BaseModel):
    is_relevant: bool


class AzureOpenAIService:
    def __init__(self):
        self.settings = get_settings()
        self._client: AsyncAzureOpenAI | None = None

    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            self._client = AsyncAzureOpenAI(
                api_key=self.settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=self.settings.AZURE_OPENAI_ENDPOINT,
                api_version=self.settings.AZURE_OPENAI_API_VERSION,
            )
        return self._client

    async def generate_answer(self, question: str, context: str) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    async def _stream_deltas(self, **create_kwargs) -> AsyncIterator[str]:
        client = self._get_client()
        stream = await client.chat.completions.create(**create_kwargs, stream=True)
        async for chunk in stream:
            if not chunk.choices:
                continue  # final usage-only chunk some deployments send has no choices
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def generate_answer_stream(self, question: str, context: str) -> AsyncIterator[str]:
        return self._stream_deltas(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
        )

    def generate_conversational_reply_stream(self, question: str) -> AsyncIterator[str]:
        return self._stream_deltas(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": CONVERSATIONAL_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.5,
        )

    def generate_clarification_stream(
        self, question: str, attempted_queries: list[str]
    ) -> AsyncIterator[str]:
        attempts_text = "\n".join(f"- {q}" for q in attempted_queries) or "- (none)"
        return self._stream_deltas(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": CLARIFICATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\nSearch queries already tried:\n{attempts_text}"
                    ),
                },
            ],
            temperature=0.5,
        )

    async def generate_conversational_reply(self, question: str) -> str:
        """A genuine LLM-generated reply for greetings/chitchat — not a
        canned string, so it actually responds to what the user said
        instead of always printing the same sentence."""
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": CONVERSATIONAL_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content or ""

    async def generate_clarification(
        self, question: str, attempted_queries: list[str]
    ) -> str:
        """Called when every retry has been exhausted without finding
        relevant content. Asks the LLM to explain, in natural language,
        that nothing was found and what detail would help — instead of
        surfacing the raw "excerpts do not contain..." style answer an
        ungrounded generate_answer call would produce."""
        client = self._get_client()
        attempts_text = "\n".join(f"- {q}" for q in attempted_queries) or "- (none)"
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": CLARIFICATION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Question: {question}\n\nSearch queries already tried:\n{attempts_text}"
                    ),
                },
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content or ""

    async def classify_needs_retrieval(self, question: str) -> bool:
        """Cheap intent check: does this message need a SharePoint search,
        or is it chitchat? Uses a structured output (Pydantic response
        model) instead of free text, so there's nothing to string-match —
        the SDK guarantees a well-typed `needs_retrieval` boolean or an
        exception, never an ambiguous verdict to interpret.

        Callers should default to True (search) if this call raises — an
        unnecessary search is a much smaller failure than silently
        refusing to look something up because a classifier had a weird day.
        """
        client = self._get_client()
        response = await client.beta.chat.completions.parse(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            temperature=0,
            response_format=IntentClassification,
        )
        return response.choices[0].message.parsed.needs_retrieval

    async def evaluate_relevance(self, question: str, context: str) -> bool:
        """Does the retrieved context actually contain enough to answer
        the question — not just "did search return something"? A search
        can find the right document and still hand back a snippet that
        misses the specific fact asked for (e.g. it centers on a
        different field of the same spreadsheet); a presence check alone
        can't tell the difference, but a judgment call can.

        Uses a structured output (Pydantic response model) so the verdict
        is a real typed boolean rather than a string to substring-match.
        Callers should default to True (relevant) if this call raises, so
        a flaky evaluator call doesn't force a pointless extra retry loop.
        """
        if not context.strip():
            return False  # nothing to judge — skip the call entirely

        client = self._get_client()
        response = await client.beta.chat.completions.parse(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": RELEVANCE_EVALUATOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nExcerpts:\n{context}",
                },
            ],
            temperature=0,
            response_format=RelevanceEvaluation,
        )
        return response.choices[0].message.parsed.is_relevant

    async def embed(self, text: str) -> list[float]:
        client = self._get_client()
        response = await client.embeddings.create(
            model=self.settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=text,
        )
        return response.data[0].embedding
