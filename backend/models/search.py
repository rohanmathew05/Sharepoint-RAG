"""Pydantic models for SharePoint / Microsoft Graph search."""
from pydantic import BaseModel

from backend.models.documents import SourceDocument


class SearchRequest(BaseModel):
    query: str
    max_results: int = 8


class SearchResult(BaseModel):
    """Result of a permission-aware SharePoint search for one user.

    ``results`` only ever contains documents the calling user's delegated
    Graph token was able to see — the Graph Search API itself enforces
    this, and nothing here is filtered or re-added after the fact.
    """

    query: str
    results: list[SourceDocument]
    total_found: int
