"""Pydantic schema for content drafts."""
from pydantic import BaseModel


class ContentDraft(BaseModel):
    cluster_id: str
    title: str
    slug: str
    content_markdown: str  # Full article in Markdown
    word_count: int
    target_keyword: str
    keyword_density: float  # Percentage
    meta_description: str
    status: str  # "draft", "needs_review"


class ContentDraftsSchema(BaseModel):
    total_drafts: int
    drafts: list[ContentDraft]
