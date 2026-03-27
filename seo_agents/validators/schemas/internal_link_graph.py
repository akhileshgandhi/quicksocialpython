"""Pydantic schema for internal link graph."""
from typing import List
from pydantic import BaseModel


class InternalLink(BaseModel):
    source_url: str
    target_url: str
    anchor_text: str
    context: str  # "body_paragraph", "sidebar", "footer"
    priority: str  # "high", "medium", "low"


class InternalLinkGraphSchema(BaseModel):
    total_links: int
    links: List[InternalLink]
    orphan_pages: List[str]  # Pages with no inbound internal links
    hub_pages: List[str]  # Pages recommended as hub/pillar pages
