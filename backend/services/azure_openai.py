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

RELEVANCE_EVALUATOR_SYSTEM_PROMPT = (
    "You judge whether the provided SharePoint document excerpts contain "
    "enough information to actually answer the user's question — not "
    "just whether they're on the same general topic. If the excerpts "
    "would let someone give a real, specific answer, respond RELEVANT. "
    "If they're empty, off-topic, or only tangentially related and "
    "missing the specific information asked for, respond NOT_RELEVANT. "
    "Respond with exactly one word."
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

    async def evaluate_relevance(self, question: str, context: str) -> bool:
        """Does the retrieved context actually contain enough to answer
        the question — not just "did search return something"? A search
        can find the right document and still hand back a snippet that
        misses the specific fact asked for (e.g. it centers on a
        different field of the same spreadsheet); a presence check alone
        can't tell the difference, but a judgment call can.

        Capped at a small token budget for the same reason as
        classify_needs_retrieval — the whole response should be one word.
        Defaults to True (relevant) on an ambiguous/unparseable verdict
        or if the call itself fails, so a flaky evaluator call doesn't
        force a pointless extra retry loop.
        """
        if not context.strip():
            return False  # nothing to judge — skip the call entirely

        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": RELEVANCE_EVALUATOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nExcerpts:\n{context}",
                },
            ],
            max_tokens=10,
            temperature=0,
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
        return "NOT_RELEVANT" not in verdict

    async def embed(self, text: str) -> list[float]:
        client = self._get_client()
        response = await client.embeddings.create(
            model=self.settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=text,
        )
        return response.data[0].embedding
