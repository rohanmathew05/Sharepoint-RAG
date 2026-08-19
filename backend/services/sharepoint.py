"""Permission-aware SharePoint retrieval.

This is the only place in the app that turns a natural-language question
into a set of SharePoint documents. It always operates with a Graph token
obtained via the On-Behalf-Of flow for the requesting user, so results are
bounded by that user's real SharePoint access before anything is handed
to the RAG pipeline.
"""
from backend.auth.obo import get_graph_token_on_behalf_of
from backend.models.auth import UserContext
from backend.models.documents import SourceDocument
from backend.services.graph import GraphService


class SharePointService:
    async def search(self, user: UserContext, query: str, max_results: int = 8) -> list[SourceDocument]:
        graph_token = await get_graph_token_on_behalf_of(user)
        graph = GraphService(graph_token)
        return await graph.search_sharepoint(query, size=max_results)
