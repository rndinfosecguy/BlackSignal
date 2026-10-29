from pydantic import BaseModel
from typing import Optional, Any


class Paste(BaseModel):
    id: str
    filename: str
    source: str
    content: str
    content_type: str
    size: int
    has_passwords: bool
    has_secrets: bool
    secrets_detail: Optional[list] = None
    first_seen: str
    modified_at: Optional[str] = None


class PasteListItem(BaseModel):
    id: str
    filename: str
    source: str
    content_type: str
    size: int
    has_passwords: bool
    has_secrets: bool
    secrets_detail: Optional[list] = None
    first_seen: str
    modified_at: Optional[str] = None
    snippet: str


class SearchResponse(BaseModel):
    total: int
    page: int
    per_page: int
    total_pages: int
    results: list[dict[str, Any]]


class StatsResponse(BaseModel):
    total: int
    with_secrets: int
    with_passwords: int
    sources: int


class SourceCount(BaseModel):
    source: str
    count: int


class TypeCount(BaseModel):
    content_type: str
    count: int