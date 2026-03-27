"""Pydantic schema for site inventory."""
from typing import List, Optional
from pydantic import BaseModel, Field


class PageRecord(BaseModel):
    url: str
    status_code: int
    title: Optional[str] = None
    meta_description: Optional[str] = None
    h1: Optional[str] = None
    word_count: int
    response_time_ms: int
    internal_links: List[str] = []
    external_links: List[str] = []


class CrawlError(BaseModel):
    url: str
    error: str


class SiteInventorySchema(BaseModel):
    total_pages: int
    crawl_depth_reached: int
    pages: List[PageRecord]
    crawl_errors: List[CrawlError] = []
