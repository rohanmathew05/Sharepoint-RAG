"""Azure OpenAI client wrapper for chat generation and embeddings.

Credentials are read from environment variables server-side only (see
backend/core/config.py) and are never returned to, or reachable from, the
React frontend.
"""
from openai import AsyncAzureOpenAI

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
    "thanks, or other chitchat that needs no document search. Respond "
    "with exactly one word: SEARCH or CHITCHAT."
)


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

    async def classify_needs_retrieval(self, question: str) -> bool:
        """Cheap intent check: does this message need a SharePoint search,
        or is it chitchat? Capped at a small token budget since the whole
        response should be one word — this is meant to cost near-nothing
        compared to an actual generation call.

        Defaults to True (search) on an ambiguous or unparseable verdict —
        an unnecessary search is a much smaller failure than silently
        refusing to look something up because a classifier had a weird day.
        """
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": INTENT_CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            max_tokens=10,
            temperature=0,
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
        return "CHITCHAT" not in verdict

    async def embed(self, text: str) -> list[float]:
        client = self._get_client()
        response = await client.embeddings.create(
            model=self.settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=text,
        )
        return response.data[0].embedding
