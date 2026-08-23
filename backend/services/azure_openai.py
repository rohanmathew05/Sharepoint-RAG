"""Azure OpenAI client wrapper for chat generation and embeddings.

Credentials are read from environment variables server-side only (see
backend/core/config.py) and are never returned to, or reachable from, the
React frontend.

The plain-text generation calls (generate_answer, streaming, conversational
replies, clarification) go straight through the OpenAI SDK. The
classification/evaluation/citation-selection calls instead go through
pydantic_ai Agents (see the bottom of this file): they already needed a
typed, validated response (IntentClassification, RelevanceEvaluation,
EntityExtraction, CitationSelection), and pydantic_ai's output_type
validates the model's tool-call arguments against those same Pydantic
models and retries automatically on a malformed response, instead of us
hand-parsing client.beta.chat.completions.parse() output. Every agent
reuses the one AsyncAzureOpenAI client from _get_client() below, so
Azure auth/config stays in one place.
"""
from typing import AsyncIterator

from openai import AsyncAzureOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

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

ENTITY_EXTRACTOR_SYSTEM_PROMPT = (
    "You decide whether a user's message is asking to compare two or more "
    "distinct named things (e.g. sites, documents, projects, people) "
    "against each other. If so, list each thing being compared as a short "
    "search phrase — its name only, not the comparison verb or connecting "
    "words (e.g. for \"compare neilstown and ronanstown\" the entities are "
    "\"neilstown\" and \"ronanstown\"). If the message is not a comparison "
    "between multiple named things, return is_comparison=false and an "
    "empty entities list."
)

COMPARISON_SYSTEM_PROMPT = (
    "You are an internal company AI assistant. The user asked a question "
    "comparing multiple named items. The context below is organized into "
    "labeled sections, one per item, built ONLY from the provided "
    "SharePoint document excerpts. If a section says no documents were "
    "found for that item, say so plainly in your answer — do not guess "
    "at its contents, and do not silently leave it out of the comparison. "
    "Compare the items using only what each section actually contains. "
    "Do not invent facts, and do not reference documents that are not "
    "listed in the context, even if you believe they exist."
)

CITATION_SELECTOR_SYSTEM_PROMPT = (
    "You will see an answer that was just written, and a list of candidate "
    "SharePoint documents that were available to it, each tagged with an "
    "id. Return only the ids of documents whose content was actually used "
    "to support a claim in the answer. Exclude any document that was "
    "retrieved or on-topic but not actually drawn from — being available "
    "is not enough, it must have genuinely contributed to what the answer "
    "says."
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


class EntityExtraction(BaseModel):
    is_comparison: bool
    entities: list[str]


class CitationSelection(BaseModel):
    used_document_ids: list[str]


class AzureOpenAIService:
    def __init__(self):
        self.settings = get_settings()
        self._client: AsyncAzureOpenAI | None = None
        self._model: OpenAIModel | None = None
        self._intent_agent: Agent[None, IntentClassification] | None = None
        self._relevance_agent: Agent[None, RelevanceEvaluation] | None = None
        self._entity_agent: Agent[None, EntityExtraction] | None = None
        self._citation_agent: Agent[None, CitationSelection] | None = None

    def _get_client(self) -> AsyncAzureOpenAI:
        if self._client is None:
            self._client = AsyncAzureOpenAI(
                api_key=self.settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=self.settings.AZURE_OPENAI_ENDPOINT,
                api_version=self.settings.AZURE_OPENAI_API_VERSION,
            )
        return self._client

    def _get_model(self) -> OpenAIModel:
        # Wraps the same AsyncAzureOpenAI client the plain-text methods use,
        # so structured-output calls go through identical Azure auth/config.
        if self._model is None:
            self._model = OpenAIModel(
                self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
                provider=OpenAIProvider(openai_client=self._get_client()),
            )
        return self._model

    def _get_intent_agent(self) -> "Agent[None, IntentClassification]":
        if self._intent_agent is None:
            self._intent_agent = Agent(
                self._get_model(),
                output_type=IntentClassification,
                instructions=INTENT_CLASSIFIER_SYSTEM_PROMPT,
            )
        return self._intent_agent

    def _get_relevance_agent(self) -> "Agent[None, RelevanceEvaluation]":
        if self._relevance_agent is None:
            self._relevance_agent = Agent(
                self._get_model(),
                output_type=RelevanceEvaluation,
                instructions=RELEVANCE_EVALUATOR_SYSTEM_PROMPT,
            )
        return self._relevance_agent

    def _get_entity_agent(self) -> "Agent[None, EntityExtraction]":
        if self._entity_agent is None:
            self._entity_agent = Agent(
                self._get_model(),
                output_type=EntityExtraction,
                instructions=ENTITY_EXTRACTOR_SYSTEM_PROMPT,
            )
        return self._entity_agent

    def _get_citation_agent(self) -> "Agent[None, CitationSelection]":
        if self._citation_agent is None:
            self._citation_agent = Agent(
                self._get_model(),
                output_type=CitationSelection,
                instructions=CITATION_SELECTOR_SYSTEM_PROMPT,
            )
        return self._citation_agent

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

    async def generate_comparison_answer(self, question: str, context: str) -> str:
        client = self._get_client()
        response = await client.chat.completions.create(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": COMPARISON_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""

    def generate_comparison_answer_stream(self, question: str, context: str) -> AsyncIterator[str]:
        return self._stream_deltas(
            model=self.settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            messages=[
                {"role": "system", "content": COMPARISON_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Context:\n{context}\n\nQuestion: {question}",
                },
            ],
            temperature=0.2,
        )

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
        result = await self._get_intent_agent().run(
            question, model_settings=ModelSettings(temperature=0)
        )
        return result.output.needs_retrieval

    async def classify_entities(self, question: str) -> EntityExtraction:
        """Does this question compare two or more distinct named things,
        and if so, what are they? Only called when a cheap string
        pre-filter already suspects comparison phrasing (see
        LangGraphRAGService._analyze_query), so this cost is never paid
        on the common single-topic question.

        Callers should treat any exception as "not a comparison" — a
        classifier hiccup should just fall back to today's single-search
        behavior, never break the pipeline.
        """
        result = await self._get_entity_agent().run(
            question, model_settings=ModelSettings(temperature=0)
        )
        return result.output

    async def select_used_citations(self, answer: str, candidates_block: str) -> list[str]:
        """Which of the retrieved documents did the already-written
        answer actually draw from? Search can legitimately return
        several plausible documents; citing all of them regardless of
        whether the answer used them misrepresents what the answer is
        actually grounded in. Called once per composed answer, never
        per search attempt.

        Callers should treat any exception, or an empty result, as "keep
        every citation" — a flaky or overly-strict filter call should
        never leave a real, grounded answer with zero sources.
        """
        result = await self._get_citation_agent().run(
            f"Answer:\n{answer}\n\nCandidate documents:\n{candidates_block}",
            model_settings=ModelSettings(temperature=0),
        )
        return result.output.used_document_ids

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

        result = await self._get_relevance_agent().run(
            f"Question: {question}\n\nExcerpts:\n{context}",
            model_settings=ModelSettings(temperature=0),
        )
        return result.output.is_relevant

    async def embed(self, text: str) -> list[float]:
        client = self._get_client()
        response = await client.embeddings.create(
            model=self.settings.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=text,
        )
        return response.data[0].embedding
