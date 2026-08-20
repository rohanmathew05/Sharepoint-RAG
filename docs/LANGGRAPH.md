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
`is_relevant`, `retrieval_attempts`, `answer`, `citations`).
`add_conditional_edges` drives both the classify/skip branch and the
relevant/rewrite branch shown above.

`classify_intent` exists because Graph's Search API returns *some*
document for almost any query string, by design (its relevance ranking
doesn't require a strong match) — without this check, a message like
"hello" reached SharePoint search and came back with citations that had
nothing to do with what was actually asked.

The classification itself is a genuine (tiny) LLM call —
`AzureOpenAIService.classify_needs_retrieval`, capped at `max_tokens=10`
and `temperature=0` since the entire response is meant to be one word
(`SEARCH` or `CHITCHAT`). Intent is a judgment call a classifier handles
better than a fixed word-list ever could ("what's the deadline" vs.
"what's up"), and at ~10 output tokens it costs a small fraction of an
actual generation call.

If that call fails for any reason, `_classify_intent` falls back to
`_is_chitchat`: an exact match against a small greeting/chitchat set,
never a substring match, so a real question that happens to contain a
greeting-like word ("hi-vis vest requirements") isn't misclassified.
This is resilience for a failed classifier call, not a demo mode — this
app always talks to real Azure OpenAI/Graph, there is no offline path.
Either outcome routes chitchat to a canned reply with no Graph call at
all.

## Where each requirement from the spec is implemented

| Capability | Implementation |
|---|---|
| Query rewriting | `LangGraphRAGService._rewrite_query` / `_llm_rewrite_query` |
| Retrieval evaluation | `LangGraphRAGService._evaluate` |
| Multiple retrieval attempts | `search` ⇄ `rewrite_query` loop, capped by `MAX_RETRIES` |
| Conditional routing | `_route_after_evaluate` and `_route_after_classify` via `add_conditional_edges` |
| Tool-use-style judgment call | `_classify_intent` / `AzureOpenAIService.classify_needs_retrieval` — LLM decides whether to invoke the SharePoint search "tool" at all |
| Conversation state | `RAGState` passed through every node |

Follow-up question handling and tool calling are natural next steps on
this same graph (e.g. a `conversation_history`-aware `analyze_query`
node, or a `tool` node for structured lookups) but aren't required for
the current permission-aware retrieval demo, so they're left out to keep
the graph's purpose — better retrieval, not a bigger tech list — clear.

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
