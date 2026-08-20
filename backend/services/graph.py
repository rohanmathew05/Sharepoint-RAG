"""Thin wrapper around the Microsoft Graph Search API.

Every call here takes a *delegated* Graph access token (obtained via the
OBO flow in backend/auth/obo.py) and is made with that token — never an
application-only token. That is what makes retrieval permission-aware:
Microsoft Graph evaluates the query against the calling user's own
SharePoint access, and results the user cannot see are simply absent from
the response. This service does not do any of its own filtering; it
passes through exactly what Graph returns.
"""
import logging

import httpx
import jwt

from backend.core.config import get_settings
from backend.models.documents import DriveInfo, SiteInfo, SourceDocument

GRAPH_SEARCH_URL = "https://graph.microsoft.com/v1.0/search/query"

logger = logging.getLogger("backend.services.graph")

# Question words / filler that add nothing as search terms and, worse,
# actively hurt recall: KQL (the query language behind Graph's Search
# API) defaults to AND between bare terms, so passing a raw natural-
# language question straight through requires every one of these common
# words to also appear in the matching document — which is why "what
# date was the last site in X done?" was reliably returning zero hits
# for real content that plainly discusses X.
_STOPWORDS = {
    "the", "and", "for", "are", "what", "when", "where", "how", "does",
    "did", "do", "with", "that", "this", "have", "has", "can", "you",
    "your", "all", "any", "who", "why", "was", "were", "which", "our",
    "about", "please", "tell", "show", "me", "was", "in", "on", "of",
    "to", "a", "is", "it", "last", "done",
}


def _build_kql_query(question: str) -> str:
    """Turns a natural-language question into a Graph/KQL search string:
    strips stopwords, then OR's the remaining keywords together so a
    document needs to match at least one of them rather than the entire
    sentence verbatim. Graph still relevance-ranks OR results, so the
    best matches surface first even though recall is intentionally
    looser than the default AND behavior.
    """
    keywords = [
        w.strip('?.,!"\'')
        for w in question.split()
        if len(w) > 2 and w.strip('?.,!"\'').lower() not in _STOPWORDS
    ]
    if not keywords:
        return question
    return " OR ".join(keywords)


def _log_token_scopes(token: str) -> None:
    """Logs the delegated permissions actually carried by the OBO-derived
    Graph token — not the token itself. Microsoft Search silently returns
    total: 0 (a normal 200, not a 403) when the calling token lacks
    sufficient permission, which is indistinguishable from "nothing
    matched" unless you can see what the token was actually granted.
    Compare this against what Graph Explorer's own token carries for the
    same query, or check the app registration's API permissions blade for
    Sites.Read.All showing a green "Granted" status, not a warning icon.
    """
    try:
        # Decoding without verifying the signature is fine here — we only
        # want to read the scp claim for a log line, not authenticate
        # anything with it.
        claims = jwt.decode(token, options={"verify_signature": False})
        logger.info("Graph token scopes (scp claim): %s", claims.get("scp", "<missing>"))
    except jwt.PyJWTError as exc:
        logger.warning("Could not decode Graph token to log its scopes: %s", exc)


class GraphAPIError(Exception):
    """Raised when Microsoft Graph itself returns a non-2xx response —
    as opposed to an OBO/auth failure (see backend/auth/obo.py), this
    means the token was fine but the request to Graph failed for some
    other reason (rate limiting, a transient 5xx, a malformed query)."""

    def __init__(self, message: str, status_code: int, retry_after: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


class GraphService:
    def __init__(self, graph_token: str):
        self.graph_token = graph_token
        self.settings = get_settings()

    async def search_sharepoint(self, query: str, size: int = 8) -> list[SourceDocument]:
        if self.settings.DEMO_MODE:
            from backend.services.demo_data import search_demo_documents

            user_oid = self.graph_token.split("::", 1)[-1]
            return search_demo_documents(user_oid, query, size)

        kql_query = _build_kql_query(query)
        body = {
            "requests": [
                {
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": kql_query},
                    "from": 0,
                    "size": size,
                }
            ]
        }
        headers = {
            "Authorization": f"Bearer {self.graph_token}",
            "Content-Type": "application/json",
        }
        logger.info("Graph search request: original=%r kql=%r size=%d", query, kql_query, size)
        _log_token_scopes(self.graph_token)

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(GRAPH_SEARCH_URL, json=body, headers=headers)

        logger.info("Graph search response: status=%d", resp.status_code)
        # Full raw body at DEBUG (set `logging.getLogger("backend.services.graph").setLevel(logging.DEBUG)`
        # or LOG_LEVEL=DEBUG in your run command) — this can contain
        # document names/snippets, so it's not logged at INFO by default.
        logger.debug("Graph search raw response body: %s", resp.text[:4000])

        if resp.status_code == 429:
            # Graph's Search API has fairly tight rate limits — this is
            # not a permission or auth problem, just "try again shortly".
            raise GraphAPIError(
                "Microsoft Graph rate-limited this request. Please try again in a moment.",
                status_code=429,
                retry_after=resp.headers.get("Retry-After"),
            )
        if resp.is_error:
            raise GraphAPIError(
                f"Microsoft Graph search failed: {resp.status_code} {resp.text[:300]}",
                status_code=resp.status_code,
            )

        payload = resp.json()

        results: list[SourceDocument] = []
        hits_containers = payload.get("value", [{}])[0].get("hitsContainers", [])
        total = sum(c.get("total", 0) for c in hits_containers)
        more_available = any(c.get("moreResultsAvailable") for c in hits_containers)
        logger.info(
            "Graph search parsed: %d hitsContainers, total=%d, moreResultsAvailable=%s",
            len(hits_containers),
            total,
            more_available,
        )
        for container in hits_containers:
            for hit in container.get("hits", []):
                resource = hit.get("resource", {})
                parent = resource.get("parentReference", {})
                results.append(
                    SourceDocument(
                        document_id=resource.get("id", ""),
                        document_name=resource.get("name", "Untitled"),
                        web_url=resource.get("webUrl", ""),
                        site=SiteInfo(
                            site_id=parent.get("siteId", ""),
                            site_name=parent.get("siteId", ""),
                            site_url=resource.get("webUrl", ""),
                        )
                        if parent.get("siteId")
                        else None,
                        drive=DriveInfo(
                            drive_id=parent.get("driveId", ""),
                            drive_name=parent.get("driveId", ""),
                        )
                        if parent.get("driveId")
                        else None,
                        relevant_content=hit.get("summary", ""),
                        last_modified=resource.get("lastModifiedDateTime"),
                    )
                )
        logger.info(
            "Graph search returned %d document(s): %s",
            len(results),
            [d.document_name for d in results],
        )
        return results
