# Architecture

## Request flow (real Azure deployment)

```
┌──────────┐  1. sign in (MSAL)          ┌──────────────────┐
│  React   │ ───────────────────────────▶│ Microsoft Entra   │
│ frontend │◀─────────────────────────── │       ID          │
└────┬─────┘   access token               └──────────────────┘
     │
     │ 2. POST /api/chat  (Authorization: Bearer <entra token>)
     ▼
┌──────────────────┐
│  FastAPI backend  │
│                    │
│  auth/entra.py     │ 3. validate token → UserContext
│  auth/obo.py        │ 4. OBO exchange (MSAL ConfidentialClientApplication)
│  services/sharepoint│ 5. call Graph with delegated token
│  services/graph.py  │
│  services/rag.py    │ 6. assemble RAG context from returned documents only
│  services/azure_openai│ 7. call Azure OpenAI with that context
└─────────┬──────────┘
          │ 5.
          ▼
┌───────────────────┐
│ Microsoft Graph     │  Search API evaluates the query against the
│ /search/query        │  caller's own SharePoint permissions
└─────────┬───────────┘
          │
          ▼
┌───────────────────┐
│    SharePoint       │
└───────────────────┘
```

## Why the LLM cannot leak unauthorised documents

The set of documents that can influence a generated answer is fixed the
moment `SharePointService.search()` returns:

```python
# backend/services/rag.py
documents = await self.sharepoint.search(user, question, max_results=...)
rag_context = RAGContext(question=question, source_documents=documents, ...)
answer = await self.llm.generate_answer(question, rag_context.prompt_context)
```

- `documents` comes from a Graph call made with a token obtained via OBO
  *for this specific user* (`backend/auth/obo.py`). Microsoft Graph — not
  application code — decides which documents are visible.
- `RAGContext.prompt_context` is built exclusively from
  `source_documents` (`backend/services/rag.py::_build_context`). There is
  no code path that injects additional text into the prompt.
- Citations returned to the frontend are derived 1:1 from the same
  `documents` list — a document can never be cited unless it was also
  part of the LLM's context.

Even if the LLM "knows" something about a topic from its training data,
the system prompt instructs it to answer only from the supplied context
and to say so when the context is insufficient
(`backend/services/azure_openai.py::SYSTEM_PROMPT`) — but the permission
boundary itself does not depend on the model following that instruction,
since unauthorised text is never placed in the prompt to begin with.

## Pydantic models

All request/response and internal data flowing through the API is typed
with Pydantic (`backend/models/`):

| Model | Purpose |
|---|---|
| `UserContext` | The authenticated caller, derived from a validated token |
| `SearchRequest` / `SearchResult` | Raw SharePoint search request/response |
| `SourceDocument` | Full metadata for one retrieved document |
| `RAGContext` | The exact context assembled for one generation call |
| `ChatRequest` / `ChatResponse` | Chat API request/response |
| `Citation` | Minimal per-source data returned to the frontend |
| `ErrorResponse` | Structured error payloads |

## Frontend

- `AuthenticatedTemplate` / `UnauthenticatedTemplate` (MSAL React) gate the
  chat UI behind Microsoft sign-in in production mode.
- The frontend never holds an Azure OpenAI key or a Graph token — it only
  ever holds its own Entra ID access token, which it sends to the FastAPI
  backend on each request. The backend performs the OBO exchange.
- `src/components/UserSwitcher.tsx` only exists for `DEMO_MODE` (no Entra
  ID app registration configured) and is not part of the production auth
  path.

## Deployment target

Designed to run locally first, then move to Azure:

- Frontend → Azure Static Web Apps
- Backend → Azure App Service / Container Apps
- Entra ID App Registration → exposes an API scope for the frontend to
  request, and delegated `Sites.Read.All` (or narrower, e.g.
  `Sites.Selected`) Graph permission for the backend's OBO exchange.
- Azure OpenAI → same resource referenced by the `AZURE_OPENAI_*` env vars
