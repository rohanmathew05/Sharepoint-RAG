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
from backend.services.url_utils import as_browser_viewable_url, folder_path_from_web_url

GRAPH_SEARCH_URL = "https://graph.microsoft.com/v1.0/search/query"

logger = logging.getLogger("backend.services.graph")

def _build_kql_query(question: str) -> str:
    """Passes the question through to Graph's Search API almost as-is.

    An earlier version of this function stripped stopwords and OR'd the
    remaining keywords together, on the theory that KQL defaults to
    AND-ing bare terms and a full sentence would rarely match anything.
    That theory turned out to be wrong: Graph's relevance ranking handles
    full natural-language queries well on its own (confirmed against
    real content — a full question returned hundreds of sensibly-ranked
    hits), and forcibly OR-ing individual keywords together throws away
    whatever phrase/proximity signal Graph's own ranking was using,
    likely making results *worse*, not better. Only trim whitespace.
    """
    return question.strip()


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
                raw_web_url = resource.get("webUrl", "")
                # A driveItem has either a "file" or a "folder" facet —
                # Graph search can match folder names too, not just files.
                is_folder = "folder" in resource
                results.append(
                    SourceDocument(
                        document_id=resource.get("id", ""),
                        document_name=resource.get("name", "Untitled"),
                        web_url=as_browser_viewable_url(raw_web_url),
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
                        is_folder=is_folder,
                        folder_path=folder_path_from_web_url(raw_web_url, is_folder),
                    )
                )
        logger.info(
            "Graph search returned %d document(s): %s",
            len(results),
            [d.document_name for d in results],
        )
        return results
