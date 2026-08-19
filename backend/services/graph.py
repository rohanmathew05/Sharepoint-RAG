"""Thin wrapper around the Microsoft Graph Search API.

Every call here takes a *delegated* Graph access token (obtained via the
OBO flow in backend/auth/obo.py) and is made with that token — never an
application-only token. That is what makes retrieval permission-aware:
Microsoft Graph evaluates the query against the calling user's own
SharePoint access, and results the user cannot see are simply absent from
the response. This service does not do any of its own filtering; it
passes through exactly what Graph returns.
"""
import httpx

from backend.core.config import get_settings
from backend.models.documents import DriveInfo, SiteInfo, SourceDocument

GRAPH_SEARCH_URL = "https://graph.microsoft.com/v1.0/search/query"


class GraphService:
    def __init__(self, graph_token: str):
        self.graph_token = graph_token
        self.settings = get_settings()

    async def search_sharepoint(self, query: str, size: int = 8) -> list[SourceDocument]:
        if self.settings.DEMO_MODE:
            from backend.services.demo_data import search_demo_documents

            user_oid = self.graph_token.split("::", 1)[-1]
            return search_demo_documents(user_oid, query, size)

        body = {
            "requests": [
                {
                    "entityTypes": ["driveItem"],
                    "query": {"queryString": query},
                    "from": 0,
                    "size": size,
                    "fields": [
                        "id",
                        "name",
                        "webUrl",
                        "lastModifiedDateTime",
                        "parentReference",
                        "siteId",
                    ],
                }
            ]
        }
        headers = {
            "Authorization": f"Bearer {self.graph_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(GRAPH_SEARCH_URL, json=body, headers=headers)
            resp.raise_for_status()
            payload = resp.json()

        results: list[SourceDocument] = []
        hits_containers = payload.get("value", [{}])[0].get("hitsContainers", [])
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
        return results
