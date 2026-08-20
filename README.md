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
flow. `docs/SETUP.md` covers setting up two test users with different
SharePoint access to verify two users genuinely get different results
for the same question.

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
    ├── components/  # ChatWindow, MessageBubble, SourceCard, FileTypeIcon
    ├── api/         # backend API client
    └── App.tsx
```

## Setup and running

This app always talks to real Microsoft Entra ID, Microsoft Graph, and
Azure OpenAI — there's no local/offline mode. See
[`docs/SETUP.md`](docs/SETUP.md) for the full walkthrough:
- Registering an Entra ID app with delegated Graph permissions
- Configuring the OBO flow (client secret, API exposure, scopes)
- Azure OpenAI environment variables
- Setting up two test users with different SharePoint access, to verify
  the permission model for real

**Backend** (from the repo root — the code uses absolute imports like
`from backend.api import ...`, which need the repo root on `sys.path`,
not `backend/` itself):

```bash
python -m venv backend/.venv && source backend/.venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env   # then fill in real credentials
uvicorn backend.main:app --reload --port 8000
```

(On Windows PowerShell: `backend\.venv\Scripts\Activate.ps1` instead of
the `source` line.)

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local   # then fill in your Entra ID app details
npm run dev
```

## Security properties this project demonstrates

- Microsoft Entra ID authentication (delegated, not app-only)
- OAuth 2.0 On-Behalf-Of flow for calling Graph as the signed-in user
- Permission-aware SharePoint retrieval — enforced by Graph, not by the LLM
- No unauthorised document ever enters the LLM's context window
- Azure OpenAI credentials stay server-side; never shipped to the browser
- Source citations link back to the original SharePoint document

## Roadmap / V2

A LangGraph-based multi-step retrieval pipeline (query rewriting,
retrieval evaluation, conditional re-search) lives on the
`feature/langgraph-orchestration` branch — see that branch's README
section for details. It layers on top of the same permission-aware
`SharePointService`, so the security guarantees above are unchanged.
