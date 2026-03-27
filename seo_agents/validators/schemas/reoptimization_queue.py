"""Pydantic schema for re-optimization queue."""
from typing import List
from pydantic import BaseModel


class ReoptItem(BaseModel):
    url: str
    target_keyword: str
    reason: str  # Why re-optimization is needed
    suggested_action: str  # "update_content", "refresh_meta", "add_internal_links"
    priority: str  # "high", "medium", "low"


class ReoptimizationQueueSchema(BaseModel):
    total_items: int
    items: List[ReoptItem]
