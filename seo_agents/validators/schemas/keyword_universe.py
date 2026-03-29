"""
Pydantic schema for keyword universe (Agent 05 output).

Includes AEO/GEO enhancements:
- query_format: keyword, question, conversational, voice
- answer_surfaces: featured_snippet, voice_assistant, ai_overview, ai_chat
- citation_value_score: 1-10 (how valuable is this for AI citations)
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class KeywordIntent(str, Enum):
    """Keyword intent classification."""
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


class VolumeTier(str, Enum):
    """Relative search volume tier."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompetitionTier(str, Enum):
    """Keyword competition tier."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class KeywordSource(str, Enum):
    """Source of the keyword."""
    SEED = "seed"
    SITE_INVENTORY = "site_inventory"
    EXPANSION = "expansion"
    QUESTION_VARIANT = "question_variant"


class QueryFormat(str, Enum):
    """Format type of the keyword query."""
    KEYWORD = "keyword"
    QUESTION = "question"
    CONVERSATIONAL = "conversational"
    VOICE = "voice"


class AnswerSurface(str, Enum):
    """Answer surface where this keyword might appear."""
    FEATURED_SNIPPET = "featured_snippet"
    VOICE_ASSISTANT = "voice_assistant"
    AI_OVERVIEW = "ai_overview"
    AI_CHAT = "ai_chat"


class KeywordEntry(BaseModel):
    """Individual keyword entry with full metadata."""
    keyword: str = Field(..., description="The keyword phrase")
    intent: KeywordIntent = Field(..., description="Search intent")
    volume_tier: VolumeTier = Field(..., description="Relative search volume")
    competition_tier: CompetitionTier = Field(..., description="Competition level")
    source: KeywordSource = Field(..., description="Where the keyword came from")
    query_format: QueryFormat = Field(
        default=QueryFormat.KEYWORD,
        description="Format: keyword, question, conversational, or voice"
    )
    answer_surfaces: List[AnswerSurface] = Field(
        default_factory=list,
        description="Where this keyword might trigger AI answers"
    )
    citation_value_score: int = Field(
        default=5,
        ge=1,
        le=10,
        description="How valuable is this keyword for AI citations (1-10)"
    )


class KeywordUniverseSchema(BaseModel):
    """Complete keyword universe with AEO/GEO enhancements."""
    total_keywords: int = Field(..., description="Total count of keywords")
    keywords: List[KeywordEntry] = Field(..., description="List of keyword entries")
    seed_terms_used: List[str] = Field(
        default_factory=list,
        description="Original seed terms used for expansion"
    )
    # AEO/GEO summary fields
    featured_snippet_opportunities: int = Field(
        default=0,
        description="Count of keywords with featured snippet potential"
    )
    voice_search_opportunities: int = Field(
        default=0,
        description="Count of keywords suitable for voice search"
    )
    ai_overview_opportunities: int = Field(
        default=0,
        description="Count of keywords suitable for AI Overviews"
    )
    high_citation_value_keywords: int = Field(
        default=0,
        description="Count of keywords with citation_value_score >= 8"
    )


__all__ = [
    "KeywordIntent",
    "VolumeTier", 
    "CompetitionTier",
    "KeywordSource",
    "QueryFormat",
    "AnswerSurface",
    "KeywordEntry",
    "KeywordUniverseSchema",
]
