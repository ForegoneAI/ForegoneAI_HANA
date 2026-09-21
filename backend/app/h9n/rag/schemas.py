"""Pydantic request and response models for H9N's retrieval-only RAG API."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# These categories make later filtering and evaluation possible without
# pretending every source has the same level of human verification.
RagSourceType = Literal[
    "deal_package",
    "analyst_note",
    "investment_criteria",
    "decision",
    "outcome",
    "other",
]


class PageText(BaseModel):
    """Text from one source page, retained so retrieval always has provenance."""

    model_config = ConfigDict(str_strip_whitespace=True)

    page_number: int = Field(gt=0)
    text: str = Field(min_length=1, max_length=25_000)


class RagIngestTextRequest(BaseModel):
    """Indexes page-preserved text for an internal or approved knowledge source."""

    model_config = ConfigDict(str_strip_whitespace=True)

    organization_id: UUID
    document_name: str = Field(min_length=1, max_length=255)
    pages: list[PageText] = Field(min_length=1, max_length=1_000)
    deal_id: UUID | None = None
    source_type: RagSourceType = "other"
    # This flag lets callers distinguish raw source material from analyst-verified knowledge.
    is_verified_knowledge: bool = False

    @field_validator("document_name")
    @classmethod
    def document_name_must_be_a_file_name(cls, value: str) -> str:
        """Reject path-like names so a document title cannot become a storage path."""
        if "/" in value or "\\" in value:
            raise ValueError("document_name must be a file name, not a path.")
        return value

    @model_validator(mode="after")
    def document_text_must_fit_the_first_pilot_limit(self) -> "RagIngestTextRequest":
        """Keep the JSON text route bounded even when it is used without a PDF upload."""
        if sum(len(page.text) for page in self.pages) > 25_000_000:
            raise ValueError("Text documents may contain at most 25,000,000 characters.")
        return self


class RagIngestResponse(BaseModel):
    """Describes the new indexed document without echoing confidential text."""

    document_id: UUID
    chunk_count: int
    page_count: int
    source_type: RagSourceType
    storage_path: str | None = None


class RagSearchRequest(BaseModel):
    """Searches only one organization's RAG corpus and returns source passages."""

    model_config = ConfigDict(str_strip_whitespace=True)

    organization_id: UUID
    query: str = Field(min_length=3, max_length=4_000)
    deal_id: UUID | None = None
    # None means use the deployment-wide H9N_RAG_DEFAULT_MATCH_COUNT setting.
    match_count: int | None = Field(default=None, ge=1, le=20)
    # Defaulting to false permits a user to search original deal documents while
    # making the source category visible in every result.
    verified_knowledge_only: bool = False


class RagSearchResult(BaseModel):
    """A retrieved passage plus the metadata needed to review its source."""

    document_id: UUID
    document_name: str
    deal_id: UUID | None = None
    source_type: RagSourceType
    is_verified_knowledge: bool
    page_number: int
    chunk_index: int
    content: str
    similarity: float


class RagSearchResponse(BaseModel):
    """Retrieval-only response; a future answer generator must cite these results."""

    results: list[RagSearchResult]
