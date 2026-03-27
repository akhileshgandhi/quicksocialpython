"""Pydantic schema for performance dashboard."""
from typing import List
from pydantic import BaseModel


class PagePerformance(BaseModel):
    url: str
    target_keyword: str
    current_title: str
    current_word_count: int
    response_time_ms: int
    implementation_status: str  # "implemented", "partial", "not_started"
    trend: str  # "improving", "stable", "declining"


class PerformanceDashboardSchema(BaseModel):
    snapshot_date: str  # ISO date
    total_pages_tracked: int
    pages: List[PagePerformance]
    overall_trend: str  # "improving", "stable", "declining"
    summary: str  # LLM-generated narrative
