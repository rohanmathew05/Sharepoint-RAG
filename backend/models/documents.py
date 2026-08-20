"""Pydantic models describing SharePoint document metadata."""
from pydantic import BaseModel, Field


class SiteInfo(BaseModel):
    site_id: str
    site_name: str
    site_url: str


class DriveInfo(BaseModel):
    drive_id: str
    drive_name: str


class SourceDocument(BaseModel):
    """Metadata for a single SharePoint document surfaced by search/retrieval.

    This travels through the whole RAG pipeline unchanged so the final
    answer can cite back to the exact SharePoint file the user is already
    permitted to open.
    """

    document_id: str
    document_name: str
    web_url: str
    site: SiteInfo | None = None
    drive: DriveInfo | None = None
    relevant_content: str = Field(
        default="", description="Snippet or extracted text used as RAG context"
    )
    last_modified: str | None = None
    is_folder: bool = False
    folder_path: str = Field(
        default="", description="Breadcrumb-style path to the item's parent folder"
    )


class Citation(BaseModel):
    """A citation attached to a generated answer, referencing a SourceDocument."""

    document_id: str
    document_name: str
    web_url: str
    is_folder: bool = False
    folder_path: str = ""
