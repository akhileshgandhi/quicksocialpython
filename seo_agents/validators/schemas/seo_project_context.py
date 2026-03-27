"""Pydantic schema for SEO project context."""
from typing import List, Optional
from pydantic import BaseModel


class SEOProjectContextSchema(BaseModel):
    business_name: str
    website_url: str
    industry: str
    target_audience: List[str]
    primary_goals: List[str]
    geographic_focus: str
    competitors: List[str] = []
    brand_voice: Optional[str] = None
    key_products_services: List[str]
