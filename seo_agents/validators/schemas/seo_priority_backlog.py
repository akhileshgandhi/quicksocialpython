"""Pydantic schema for SEO priority backlog."""
from typing import List, Optional
from pydantic import BaseModel


class BacklogItem(BaseModel):
    item_id: str
    type: str  # "technical_fix", "page_optimization", "new_content"
    title: str
    description: str
    target_keyword: Optional[str] = None
    target_url: Optional[str] = None
    impact_score: int  # 1-10
    effort_score: int  # 1-10
    priority_rank: int
    phase: str  # "month_1", "month_2", "month_3_plus"


class SEOPriorityBacklogSchema(BaseModel):
    total_items: int
    items: List[BacklogItem]
    summary: str
