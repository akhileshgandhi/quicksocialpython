"""Pydantic schema for content briefs."""
from typing import List
from pydantic import BaseModel


class OutlineSection(BaseModel):
    heading: str
    level: int  # 2 or 3
    key_points: List[str]
    supporting_keywords: List[str]


class LinkSuggestion(BaseModel):
    anchor_text: str
    target_url: str


class ContentBrief(BaseModel):
    cluster_id: str
    target_keyword: str
    recommended_title: str
    recommended_slug: str
    content_type: str
    target_word_count_min: int
    target_word_count_max: int
    outline: List[OutlineSection]
    tone_guidance: str
    internal_links: List[LinkSuggestion]
    cta_suggestions: List[str]


class ContentBriefsSchema(BaseModel):
    total_briefs: int
    briefs: List[ContentBrief]
