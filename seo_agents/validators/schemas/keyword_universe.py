"""Pydantic schema for keyword universe."""
from typing import List
from pydantic import BaseModel


class KeywordEntry(BaseModel):
    keyword: str
    intent: str  # "informational", "navigational", "commercial", "transactional"
    volume_tier: str  # "high", "medium", "low"
    competition_tier: str  # "high", "medium", "low"
    source: str  # "seed", "expansion", "competitor_gap"


class KeywordUniverseSchema(BaseModel):
    total_keywords: int
    keywords: List[KeywordEntry]
    seed_terms_used: List[str]
