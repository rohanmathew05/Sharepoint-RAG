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
(`question`, `user`, `search_query`, `documents`, `is_relevant`,
`retrieval_attempts`, `answer`, `citations`). `add_conditional_edges`
drives the relevant/rewrite branch shown above.

## Where each requirement from the spec is implemented

| Capability | Implementation |
|---|---|
| Query rewriting | `LangGraphRAGService._rewrite_query` / `_llm_rewrite_query` |
| Retrieval evaluation | `LangGraphRAGService._evaluate` |
| Multiple retrieval attempts | `search` ⇄ `rewrite_query` loop, capped by `MAX_RETRIES` |
| Conditional routing | `_route_after_evaluate` via `add_conditional_edges` |
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
for, never *who* the search runs as. `backend/tests/test_langgraph_pipeline.py`
asserts this directly: a user without Engineering access still gets zero
citations from a pump-specification question after two rewritten search
attempts, while a user with access gets citations on the first attempt.

## Trying it

```bash
# same DEMO_MODE setup as the root README
curl -X POST http://localhost:8000/api/chat/v2 \
  -H "Content-Type: application/json" \
  -H "X-Demo-User: user-a" \
  -H "Authorization: Bearer demo-token" \
  -d '{"question": "What are the pump specifications?"}'
```

Response includes `retrieval_attempts` — for User A (no Engineering
access) this will be `2` (one rewrite, still no results); for User B it
will be `1`.

In the frontend, tick "Use LangGraph pipeline" above the chat input to
route requests to `/api/chat/v2` instead of `/api/chat`.
