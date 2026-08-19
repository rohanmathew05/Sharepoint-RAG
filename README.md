# Permission-Aware SharePoint RAG Assistant

An enterprise AI assistant that lets employees ask natural-language
questions about company documents stored in SharePoint — while
guaranteeing that each user only ever retrieves content they already have
permission to access in SharePoint itself.

Built with React, TypeScript, Python, FastAPI, Pydantic, Microsoft Entra
ID, OAuth 2.0 On-Behalf-Of (OBO), Microsoft Graph, SharePoint, and Azure
OpenAI.

## Why this exists

Most "chat with your docs" demos skip the hardest part of an internal
enterprise assistant: **making sure the AI never leaks information a user
isn't allowed to see.** This project treats that as the core feature, not
an afterthought — retrieval is always scoped to the requesting user's own
Microsoft 365 permissions, enforced by Microsoft Graph itself, not by the
LLM or by application-level ACL logic.

## How permission-aware retrieval works

```
User's Entra ID access token
        │
        ▼
FastAPI validates the token → UserContext
        │
        ▼
On-Behalf-Of (OBO) token exchange (MSAL)
        │
        ▼
Delegated Microsoft Graph token — scoped to THIS user
        │
        ▼
Microsoft Graph Search API (/search/query)
        │
        ▼
Only documents this user can already open in SharePoint
        │
        ▼
RAG context (source_documents) ── this is the ENTIRE candidate set for the LLM
        │
        ▼
Azure OpenAI generates an answer grounded in that context
        │
        ▼
Answer + citations linking back to the original SharePoint files
```

Nothing in the FastAPI backend re-adds or widens the document set after
retrieval. If Microsoft Graph doesn't return a document for that user's
token, it never enters the prompt sent to Azure OpenAI, and it can never
appear in the answer or its citations.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full request
flow and [`docs/PERMISSIONS_DEMO.md`](docs/PERMISSIONS_DEMO.md) for a
step-by-step demonstration of two users getting different results for the
same question.

## Project layout

```
backend/
├── api/            # FastAPI routers (auth, chat, search)
├── models/         # Pydantic models (chat, search, documents, auth)
├── services/        # graph.py, sharepoint.py, rag.py, azure_openai.py
├── auth/            # entra.py (token validation), obo.py (OBO exchange)
└── main.py

frontend/
└── src/
    ├── components/  # ChatWindow, MessageBubble, SourceCard, UserSwitcher
    ├── api/         # backend API client
    └── App.tsx
```

## Running locally (no Azure tenant required)

The project ships with `DEMO_MODE=true`, which uses local fixture
SharePoint data and two demo users instead of live Entra ID / Graph /
Azure OpenAI — so you can see the whole permission model working
end-to-end with zero cloud setup.

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, use the "Signed in as" dropdown to switch
between User A and User B, and ask the same question as each — see
[`docs/PERMISSIONS_DEMO.md`](docs/PERMISSIONS_DEMO.md) for exact examples.

## Running against real Microsoft Entra ID / Graph / Azure OpenAI

See [`docs/SETUP.md`](docs/SETUP.md) for:
- Registering an Entra ID app with delegated Graph permissions
- Configuring the OBO flow (client secret, API exposure, scopes)
- Azure OpenAI environment variables
- Setting `DEMO_MODE=false`

## Security properties this project demonstrates

- Microsoft Entra ID authentication (delegated, not app-only)
- OAuth 2.0 On-Behalf-Of flow for calling Graph as the signed-in user
- Permission-aware SharePoint retrieval — enforced by Graph, not by the LLM
- No unauthorised document ever enters the LLM's context window
- Azure OpenAI credentials stay server-side; never shipped to the browser
- Source citations link back to the original SharePoint document

## V2: LangGraph orchestration

A second RAG pipeline, `POST /api/chat/v2`, adds LangGraph-based
multi-step orchestration on top of the same permission-aware
`SharePointService`: query rewriting, retrieval evaluation, and bounded
re-search when the first attempt comes back empty. See
[`docs/LANGGRAPH.md`](docs/LANGGRAPH.md) for the graph and why it doesn't
change the security model. Toggle it in the frontend with the "Use
LangGraph pipeline" checkbox above the chat input.
