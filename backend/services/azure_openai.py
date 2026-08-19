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
        if self.settings.DEMO_MODE:
            return self._demo_answer(question, context)

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

    async def embed(self, text: str) -> list[float]:
        if self.settings.DEMO_MODE:
            return []  # demo mode uses keyword search, not embeddings

        client = self._get_client()
        response = await client.embeddings.create(
            model=self.settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=text,
        )
        return response.data[0].embedding

    @staticmethod
    def _demo_answer(question: str, context: str) -> str:
        """A small deterministic stand-in for Azure OpenAI so the RAG flow
        and citation plumbing can be demoed without live Azure credentials.
        Real deployments should never take this path (DEMO_MODE=false).
        """
        if not context.strip():
            return (
                "I couldn't find any documents you have access to that "
                "answer this question. Try rephrasing, or check with the "
                "document owner about access."
            )
        snippet = context.strip().split("\n\n")[0]
        return (
            f"Based on the documents you have access to: {snippet[:500]}"
            + ("..." if len(snippet) > 500 else "")
        )
