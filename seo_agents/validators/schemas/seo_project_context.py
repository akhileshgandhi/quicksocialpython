"""Pydantic schema for SEO project context.

Enhanced with AEO/GEO fields for Answer Engine Optimization and Generative Engine Optimization.
"""
from typing import List, Optional
from pydantic import BaseModel, Field


class SEOProjectContextSchema(BaseModel):
    # Basic business info
    business_name: str
    website_url: str
    industry: str
    target_audience: List[str] = Field(default_factory=list)
    primary_goals: List[str] = Field(default_factory=list)
    geographic_focus: str = "Global"
    competitors: List[str] = Field(default_factory=list)
    brand_voice: Optional[str] = None
    key_products_services: List[str] = Field(default_factory=list)
    
    # AEO/GEO Enhancement fields
    voice_search_goals: List[str] = Field(
        default_factory=list,
        description="Goals related to voice search optimization (e.g., 'optimize for Alexa', 'capture voice queries')"
    )
    ai_citation_targets: List[str] = Field(
        default_factory=list,
        description="Pages or content the client wants AI systems (ChatGPT, Perplexity) to cite"
    )
    featured_snippet_targets: List[str] = Field(
        default_factory=list,
        description="Keywords or queries the client wants to win featured snippets for"
    )
    target_ai_platforms: List[str] = Field(
        default_factory=list,
        description="AI platforms to optimize for: ChatGPT, Claude, Gemini, Perplexity, Bing Copilot, etc."
    )
    conversational_content_priority: bool = Field(
        default=False,
        description="Whether the client prioritizes conversational/question-based content"
    )
