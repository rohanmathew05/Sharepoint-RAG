# Setup: Real Microsoft Entra ID / Graph / Azure OpenAI

The project runs in `DEMO_MODE` by default (see root README). This guide
covers switching to a real tenant.

## 1. Register an Entra ID application

In the Azure Portal → Microsoft Entra ID → App registrations → New
registration:

1. Create the app (e.g. "SharePoint RAG Assistant"). Note the
   **Application (client) ID** and **Directory (tenant) ID**.
2. Under **Certificates & secrets**, create a client secret. This becomes
   `ENTRA_CLIENT_SECRET` — backend only, never in the frontend.
3. Under **Expose an API**:
   - Set an Application ID URI (default `api://<client-id>` is fine).
   - Add a scope, e.g. `access_as_user`, admin + user consentable.
4. Under **API permissions**, add delegated Microsoft Graph permissions:
   - `Sites.Read.All` (or `Sites.Selected` for tighter scoping to specific
     SharePoint sites) — required for `/search/query` to return
     SharePoint content.
   - Grant admin consent.
5. Under **Authentication**, add a SPA platform with redirect URI
   `http://localhost:5173` (and your deployed frontend URL later). Enable
   the SPA's implicit/authorization-code + PKCE flow (MSAL handles this).

## 2. Configure the backend

```bash
cd backend
cp .env.example .env
```

Fill in:

```env
ENTRA_TENANT_ID=<tenant id>
ENTRA_CLIENT_ID=<client id>
ENTRA_CLIENT_SECRET=<client secret>
DEMO_MODE=false
```

Also set the Azure OpenAI variables (see root README's env var list).

## 3. Configure the frontend

Create `frontend/.env.local`:

```env
VITE_ENTRA_CLIENT_ID=<client id>
VITE_ENTRA_TENANT_ID=<tenant id>
VITE_REDIRECT_URI=http://localhost:5173
```

Setting `VITE_ENTRA_CLIENT_ID` automatically switches the frontend out of
demo mode (`src/authConfig.ts::DEMO_MODE`) and into real MSAL sign-in.

## 4. Set up two test users with different SharePoint access

To reproduce the permission demo against a real tenant:

1. In SharePoint, create (or reuse) two document libraries/sites, e.g.
   "Health & Safety" (shared) and "Engineering" (restricted).
2. Create/assign two test users in Entra ID:
   - **User A**: member of the group with access to "Health & Safety"
     only.
   - **User B**: member of groups with access to both "Health & Safety"
     and "Engineering".
3. Sign in as each user in the frontend and ask the same question about
   Engineering content — User A should get no relevant sources, User B
   should get citations back to the Engineering documents.

This is the same scenario `docs/PERMISSIONS_DEMO.md` walks through in
demo mode — the only difference is that Microsoft Graph, not the fixture
table in `backend/services/demo_data.py`, is enforcing the boundary.

## 5. Run it

```bash
# backend
cd backend && uvicorn main:app --reload --port 8000

# frontend
cd frontend && npm run dev
```

## Notes on the OBO flow

`backend/auth/obo.py` uses MSAL's
`ConfidentialClientApplication.acquire_token_on_behalf_of`, passing the
frontend's access token as the `user_assertion`. This requires:

- The frontend token's `aud` claim to match your backend's exposed API
  (`api://<client-id>`).
- The backend's app registration to have the delegated Graph permissions
  listed above, with admin consent granted — OBO will fail with
  `AADSTS65001` (consent required) otherwise.

### Mid-session token expiry

The frontend's Entra ID access token and the backend's per-user cached
Graph token (obtained via OBO) both have their own lifetimes, so either
can go stale while a user is mid-session:

- `backend/auth/entra.py` checks the inbound token's `exp` claim and
  returns `401` immediately if it's expired, before ever attempting the
  OBO exchange.
- `backend/auth/obo.py` catches OBO failures and distinguishes two cases:
  `OBOTokenExpiredError` (the user's session is gone — e.g. AAD's
  `invalid_grant` / `AADSTS700082`) maps to a `401` with
  `error_code: obo_token_expired`; anything else (`OBOExchangeError` —
  bad app registration, missing consent, transient Entra ID errors) maps
  to a `502`, so a real backend misconfiguration doesn't get misread as
  "please sign in again."
- On the frontend, `App.tsx`'s `getToken()` wraps
  `acquireTokenSilent` in a try/catch: MSAL usually renews the access
  token transparently using its own refresh token, but if that also fails
  (`InteractionRequiredAuthError` — refresh token expired, conditional
  access requires fresh interaction), it redirects to sign-in instead of
  letting a doomed request reach the backend.
- `frontend/src/api/client.ts::sendChatMessage` retries a request exactly
  once if the backend responds `401` — covering the case where the
  backend's *cached OBO token* went stale independently of the frontend's
  own token, so a fresh `getToken()` call plus one retry recovers without
  the user noticing.

See `backend/tests/test_obo_expiry.py` for the behavior this produces:
an expired frontend token or a failed OBO exchange both return a typed
`401`/`502` instead of an unhandled `500`.
