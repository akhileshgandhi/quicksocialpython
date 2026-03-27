"""Pydantic schema for competitor matrix."""
from typing import List
from pydantic import BaseModel


class CompetitorProfile(BaseModel):
    name: str
    url: str
    estimated_pages: int
    content_themes: List[str]
    strengths: List[str]
    weaknesses: List[str]


class CompetitorMatrixSchema(BaseModel):
    competitors: List[CompetitorProfile]
    overlap_keywords: List[str]
    gap_opportunities: List[str]
    competitive_position: str
