# Permissions Demo

This project ships two demo users so the permission-aware retrieval model
can be verified directly, without an Azure tenant.

```
SharePoint
│
├── General               → User A ✅   User B ✅
├── Health & Safety       → User A ✅   User B ✅
├── Engineering           → User A ❌   User B ✅
└── HR                    → User A ❌   User B ❌
```

(Membership table: `backend/services/demo_data.py::GROUP_MEMBERSHIP`.
Fixture documents: `backend/services/demo_data.py::DOCUMENT_LIBRARY`.)

## Steps

1. Start the backend (`uvicorn main:app --reload --port 8000`) and
   frontend (`npm run dev`) as described in the root README.
2. Open http://localhost:5173.
3. With **User A** selected in the "Signed in as" dropdown, ask:
   > What PPE is required when working in a confined space?

   Expect an answer citing `Confined Space Policy.pdf` and
   `PPE Requirements.docx` — both in the Health & Safety group User A
   belongs to.
4. Still as **User A**, ask:
   > What are the pump specifications?

   Expect **no relevant sources** — User A is not a member of the
   Engineering group, so Engineering documents are never returned by
   `SharePointService.search()`, let alone passed to Azure OpenAI.
5. Switch to **User B** and ask the same pump question:
   > What are the pump specifications?

   Expect an answer citing `Pump Specifications.pdf` and
   `Installation Guide.pdf`.
6. Ask either user:
   > What is the company's salary policy?

   Expect no sources for both — neither demo user belongs to HR.

## Automated proof

`backend/tests/test_permissions.py` encodes the same scenarios as
assertions against the retrieval layer directly (no HTTP round trip
required):

```bash
cd backend
pytest tests/test_permissions.py -v
```

## Where the boundary actually lives

In demo mode, `backend/services/demo_data.py::search_demo_documents()`
filters candidate documents to the requesting user's `GROUP_MEMBERSHIP`
*before* any keyword scoring happens — mirroring exactly what happens
against a real tenant:

- `backend/services/sharepoint.py` always calls Graph with a token from
  `backend/auth/obo.py::get_graph_token_on_behalf_of()`, which is a
  **delegated** token for the specific requesting user (obtained via the
  On-Behalf-Of flow), never an application-only token.
- `backend/services/graph.py` calls
  `POST https://graph.microsoft.com/v1.0/search/query` with that token.
  Microsoft Graph itself evaluates the query against that user's real
  SharePoint ACLs — a document the user cannot open in SharePoint simply
  will not appear in the response.
- `backend/services/rag.py` builds the Azure OpenAI prompt only from
  whatever `SharePointService.search()` returned. There is no later step
  that adds documents back in.

So switching from `DEMO_MODE=true` to a real Entra ID tenant does not
change the security model at all — it changes which system (fixture table
vs. real SharePoint ACLs) is doing the enforcement.
