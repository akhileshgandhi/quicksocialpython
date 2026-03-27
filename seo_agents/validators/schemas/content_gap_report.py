"""Pydantic schema for content gap report."""
from typing import List
from pydantic import BaseModel


class ContentGap(BaseModel):
    cluster_id: str
    primary_keyword: str
    priority: str  # "high", "medium", "low"
    suggested_content_type: str  # "blog_post", "guide", "comparison", "FAQ", etc.
    effort_level: str  # "quick_win", "moderate", "deep_investment"
    competitor_coverage: str
    rationale: str


class ContentGapReportSchema(BaseModel):
    total_gaps: int
    gaps: List[ContentGap]
    quick_wins: List[str]  # cluster IDs
