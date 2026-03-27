"""Pydantic schema for page optimization briefs."""
from typing import List
from pydantic import BaseModel


class HeaderSuggestion(BaseModel):
    level: str  # "h2", "h3"
    text: str


class LinkSuggestion(BaseModel):
    anchor_text: str
    target_url: str


class PageOptimizationBrief(BaseModel):
    target_url: str
    target_keyword: str
    recommended_title: str
    recommended_meta_description: str
    recommended_h1: str
    recommended_headers: List[HeaderSuggestion]
    internal_link_suggestions: List[LinkSuggestion]
    image_alt_suggestions: List[str]


class PageOptimizationBriefsSchema(BaseModel):
    total_briefs: int
    briefs: List[PageOptimizationBrief]
