"""Pydantic schema for page-keyword mapping."""
from typing import List, Optional
from pydantic import BaseModel


class PageKeywordMapping(BaseModel):
    cluster_id: str
    primary_keyword: str
    assignment: str  # "existing_page", "new_page", "merge"
    existing_page_url: Optional[str] = None
    merge_into_cluster_id: Optional[str] = None
    recommended_url_slug: Optional[str] = None
    recommended_page_type: str


class PageKeywordMapSchema(BaseModel):
    mappings: List[PageKeywordMapping]
    total_existing_matches: int
    total_new_pages_needed: int
    total_merges: int
