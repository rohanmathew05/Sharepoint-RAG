# LangGraph Orchestration (V2)

`backend/services/langgraph_pipeline.py` adds a second, more capable RAG
pipeline alongside the V1 single-shot one in `backend/services/rag.py`.
Both share the same permission-aware `SharePointService` and
`AzureOpenAIService` — V2 only changes *how many times* and *with what
query* SharePoint gets searched before generating an answer.

## Why

The V1 pipeline runs one search and generates an answer from whatever
comes back — including nothing. That's fine when the user's phrasing
happens to match document content, but real questions are often phrased
differently from the documents that answer them ("what safety gear do I
need underground?" vs. a document titled "Confined Space Policy"). V2
adds a retry loop: if the first search is empty, rewrite the query and
try again before giving up.

## Graph

```
       question
          │
          ▼
   analyze_query        normalizes the question into a search query
          │
          ▼
  classify_intent       does this actually need a SharePoint search?
          │
          ├── no (greeting/chitchat) ──▶ answer_conversationally ──▶ END
          │
         yes
          │
          ▼
        search   ◀───────────────┐   SharePointService.search(user, query)
          │                       │   (OBO-gated Graph call — unchanged
          ▼                       │    permission boundary from V1)
       evaluate                   │
          │                       │
     is_relevant? ── no, retries left ──▶ rewrite_query ──┘
          │
   yes, or retries exhausted
          │
          ▼
   generate_answer
          │
          ▼
         END
```

Implemented with `langgraph.graph.StateGraph` over a typed `RAGState`
(`question`, `user`, `search_query`, `needs_retrieval`, `documents`,
`is_relevant`, `retrieval_attempts`, `previous_queries`,
`best_documents`, `best_context`, `answer`, `citations`).
`add_conditional_edges` drives both the classify/skip branch and the
relevant/rewrite branch shown above.

`previous_queries` accumulates every search query already tried this
request (`_search` appends to it on each attempt) and is fed into
`_llm_rewrite_query`'s prompt in full, not just the most recent query —
so each retry is told everything that's already failed and asked for
something *meaningfully different*, rather than rewriting blind and
risking similar phrasings across attempts.
`test_rewrite_prompt_includes_full_query_history` in
`backend/tests/test_langgraph_pipeline.py` asserts the full history
reaches the prompt.

Graph's Search API does exact-ish keyword matching, not fuzzy matching —
a single misspelled proper noun is enough to return zero results even
when a document with that exact name exists (e.g. searching "Neilstown
Community Centre" finds nothing for a real
`NEILLSTOWN COMMUNITY CENTRE.xlsx`, while "Community Centre" alone
does). Left to a generic "try a synonym or broader phrasing"
instruction, the rewrite LLM doesn't reliably think to check for a typo
first. `_llm_rewrite_query`'s prompt spells out an explicit, staged
strategy instead: (1) check every word for a possible spelling mistake,
especially proper nouns, and correct it while keeping the rest of the
query the same; (2) if a spelling-corrected version has already been
tried, drop the most specific/unusual word entirely and search on the
more generic remaining terms; (3) only after both of those, fall back to
a broader/narrower phrasing or synonym.
`test_rewrite_prompt_prioritizes_spelling_correction_before_dropping_words`
in `backend/tests/test_langgraph_pipeline.py` covers this.

`classify_intent` exists because Graph's Search API returns *some*
document for almost any query string, by design (its relevance ranking
doesn't require a strong match) — without this check, a message like
"hello" reached SharePoint search and came back with citations that had
nothing to do with what was actually asked.

The classification itself is a genuine (tiny) LLM call —
`AzureOpenAIService.classify_needs_retrieval`, at `temperature=0` since
it's a yes/no judgment call, not open-ended generation. It uses Azure
OpenAI's structured outputs (`client.beta.chat.completions.parse(...,
response_format=IntentClassification)`), so the verdict is a typed
`needs_retrieval: bool` on a Pydantic model, not a word to
substring-match — there's no ambiguous free-text response to interpret.
Intent is a judgment call a classifier handles better than a fixed
word-list ever could ("what's the deadline" vs. "what's up").

If that call fails for any reason, `_classify_intent` falls back to
`_is_chitchat`: an exact match against a small greeting/chitchat set,
never a substring match, so a real question that happens to contain a
greeting-like word ("hi-vis vest requirements") isn't misclassified.
This is resilience for a failed classifier call, not a demo mode — this
app always talks to real Azure OpenAI/Graph, there is no offline path.

Either outcome routes to `answer_conversationally`, which asks
`AzureOpenAIService.generate_conversational_reply` for a genuine
LLM-generated reply — not a hardcoded string — so the response actually
reflects what the user said rather than printing the same sentence for
every greeting. If that call fails, a fixed fallback string
(`_FALLBACK_CHITCHAT_REPLY`) is used so the user still gets a response.
No Graph call happens on this path either way.

## Where each requirement from the spec is implemented

| Capability | Implementation |
|---|---|
| Query rewriting | `LangGraphRAGService._rewrite_query` / `_llm_rewrite_query` |
| Retrieval evaluation | `LangGraphRAGService._evaluate` / `AzureOpenAIService.evaluate_relevance` — a real LLM judgment call, not a "did we get any documents back" presence check |
| Multiple retrieval attempts | `search` ⇄ `rewrite_query` loop, capped by `MAX_RETRIES` (8) |
| Conditional routing | `_route_after_evaluate` and `_route_after_classify` via `add_conditional_edges` |
| Tool-use-style judgment call | `_classify_intent` / `AzureOpenAIService.classify_needs_retrieval` — LLM decides whether to invoke the SharePoint search "tool" at all |
| Conversation state | `RAGState` passed through every node |

`_evaluate` used to be `len(documents) > 0` — did the search find *anything*.
That misses a real failure mode: Graph can find exactly the right
document and still hand back a search snippet that doesn't contain the
specific fact asked for (e.g. a spreadsheet's "GIS ID" field, when the
snippet centers on a different field of the same sheet). A presence
check calls that "relevant" and generates a confident "not found"
answer from context that was never going to answer the question. Now
`_evaluate` builds the same context `_generate_answer` will use and
asks `AzureOpenAIService.evaluate_relevance` (`temperature=0`, structured
output via `response_format=RelevanceEvaluation`) whether it actually
answers the question — not just whether it's on-topic, and not a word to
substring-match. A `is_relevant=False` verdict routes back into
`rewrite_query` exactly like an empty search would.
`test_llm_relevance_check_triggers_retry_on_unhelpful_snippet` in
`backend/tests/test_langgraph_pipeline.py` covers this directly.

### What happens when every retry is exhausted

If `retrieval_attempts` hits `MAX_RETRIES` without the *last* attempt
being judged relevant, `_route_after_evaluate` still routes to
`generate_answer` — but `_generate_answer` checks `state["is_relevant"]`
first.

Before deciding what to do, it's important that "the last attempt wasn't
relevant" is not the same as "nothing useful was ever found" — an
earlier attempt can find exactly the right document and still get
marked `is_relevant=False` (a plausible false negative, e.g. Neillstown
Community Centre files for a Neillstown Community Centre question), and
a later rewrite can then find nothing at all. If `_generate_answer` only
ever looked at the *most recent* attempt, that earlier find would be
silently discarded and the user would get a "couldn't find anything"
clarification even though a strong candidate document was sitting right
there a few attempts ago. `_evaluate` guards against this by tracking
`best_documents`/`best_context` on `RAGState` — the richest non-empty
`(documents, context)` pair seen across *any* attempt, not just the
latest — updated whenever a new attempt's context is longer than the
best one seen so far.

So `_generate_answer` branches three ways:
- `is_relevant=True` → normal grounded answer over the last attempt's
  `documents`/`prompt_context`, as before.
- `is_relevant=False` but `best_context` is non-empty → retries are
  exhausted, but something was found along the way. Give the grounded
  `generate_answer` call a real shot at `best_documents`/`best_context`
  and cite those documents — a wrong relevance verdict is a more
  forgivable failure than throwing away a real find.
- `is_relevant=False` and `best_context` is still empty → truly nothing
  was ever found. Calls
  `AzureOpenAIService.generate_clarification(question, previous_queries)`
  — a genuine LLM call, not a hardcoded string — which is told the
  question and every search query already tried, and asked to explain
  in natural language that nothing was found and suggest what specific
  detail (an exact document name, a reference number, a different term)
  would help. No citations are returned on this path. If the call
  itself fails, a fixed fallback string (`_FALLBACK_CLARIFICATION_REPLY`)
  is used instead of leaving the user with nothing.

`test_exhausted_retries_use_llm_generated_clarification` covers the
truly-nothing-found path, and
`test_exhausted_retries_fall_back_to_best_attempt_content` covers the
"earlier attempt found something, later one didn't" recovery path — both
in `backend/tests/test_langgraph_pipeline.py`.

Conversations are persisted server-side (SQLite, behind the
`ConversationStore` interface in `backend/services/storage/`) and prior
turns are threaded into `RAGState["conversation_history"]`. `analyze_query`
uses it first: `AzureOpenAIService.contextualize_query` resolves the raw
message against the conversation history into a standalone search query
(e.g. a bare follow-up like "could you find more details" becomes
"Neilstown Ronanstown details") before anything else runs, and that
resolved question — not the raw message — is what `classify_intent`, the
comparison entity extraction, and every `rewrite_query` retry reason over.
History is also passed into every rewrite attempt, not just the first, and
still flows into the final-answer generation calls
(`_answer_conversationally`, `_generate_answer`/`_prepare_generation`'s
clarification/answer/comparison branches) as before, so both retrieval and
the final answer share the same conversational grounding.

## Why this doesn't change the security model

`_search` calls the exact same `SharePointService.search()` as V1, which
always requires an OBO-derived Graph token scoped to the requesting user
(`backend/auth/obo.py`). Rewriting the query changes *what* is searched
for, never *who* the search runs as — the pipeline itself does no
filtering; `test_delegated_token_search_is_the_only_permission_boundary`
in `backend/tests/test_langgraph_pipeline.py` asserts the user object is
passed through to `SharePointService.search()` unmodified. Whether two
different users actually get different results is Microsoft Graph's
call at request time, not something unit-testable without a real
tenant — see `docs/SETUP.md`'s "Set up two test users" section to
verify it for real.

## Trying it

```bash
curl -X POST http://localhost:8000/api/chat/v2 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your Entra ID access token>" \
  -d '{"question": "What are the pump specifications?"}'
```

Response includes `retrieval_attempts` — `1` if the first search found
something relevant, higher if it had to rewrite and retry.

The frontend always routes through `/api/chat/v2` (`frontend/src/api/client.ts::CHAT_ENDPOINT`)
— there's no toggle, this is the only chat pipeline the UI calls.
