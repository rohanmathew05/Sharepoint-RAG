"""Raw permission-aware SharePoint search endpoint (no LLM involved).

Useful for demonstrating the permission model in isolation — e.g. showing
that User A and User B get different result sets for the same query,
without needing Azure OpenAI configured.
"""
from fastapi import APIRouter, Depends

from backend.auth.entra import get_current_user
from backend.models.auth import UserContext
from backend.models.search import SearchRequest, SearchResult
from backend.services.sharepoint import SharePointService

router = APIRouter(prefix="/api/search", tags=["search"])
sharepoint_service = SharePointService()


@router.post("", response_model=SearchResult)
async def search(
    request: SearchRequest, user: UserContext = Depends(get_current_user)
) -> SearchResult:
    documents = await sharepoint_service.search(user, request.query, request.max_results)
    return SearchResult(query=request.query, results=documents, total_found=len(documents))
