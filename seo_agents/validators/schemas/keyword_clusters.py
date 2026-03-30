"""
Pydantic schema for keyword clusters.

Agent 05 (ClusteringAgent) groups semantically related keywords into clusters.
Each cluster maps to exactly one target URL and one dominant answer intent.
"""
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class ClusterIntent(str, Enum):
    """Cluster-level search intent classification."""
    INFORMATIONAL = "informational"
    NAVIGATIONAL = "navigational"
    COMMERCIAL = "commercial"
    TRANSACTIONAL = "transactional"


class PageType(str, Enum):
    """Recommended page type for targeting a keyword cluster."""
    BLOG_POST = "blog_post"
    LANDING_PAGE = "landing_page"
    PRODUCT_PAGE = "product_page"
    CATEGORY_PAGE = "category_page"
    FAQ_PAGE = "faq_page"
    HOW_TO_GUIDE = "how_to_guide"


class AnswerFormat(str, Enum):
    """Recommended content format for the cluster."""
    SHORT_PARAGRAPH = "short_paragraph"
    LIST = "list"
    FAQ = "faq"
    TABLE = "table"
    STEP_BY_STEP = "step_by_step"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    TUTORIAL = "tutorial"


class AnswerSurface(str, Enum):
    """AI/serp features this cluster can target."""
    FEATURED_SNIPPET = "featured_snippet"
    VOICE_SEARCH = "voice_search"
    AI_OVERVIEW = "ai_overview"
    PEOPLE_ALSO_ASK = "people_also_ask"
    VIDEO_CAROUSEL = "video_carousel"
    IMAGE_PACK = "image_pack"
    NEWS_RESULTS = "news_results"
    LOCAL_PACK = "local_pack"


class KeywordCluster(BaseModel):
    """Single keyword cluster representing one topic for one page."""
    cluster_id: str = Field(..., description="Unique cluster identifier (e.g., cluster_001)")
    cluster_name: str = Field(..., description="Descriptive name for the cluster topic")
    
    # Keyword assignments
    primary_keyword: str = Field(..., description="Main target keyword for this cluster")
    supporting_keywords: List[str] = Field(
        default_factory=list, 
        description="All related keywords in this cluster"
    )
    
    # Intent classification
    intent: ClusterIntent = Field(..., description="Primary search intent for the cluster")
    funnel_stage: str = Field(
        default="MOFU",
        description="Funnel stage: TOFU (top), MOFU (middle), BOFU (bottom)"
    )
    
    # Volume and competition
    total_volume_tier: str = Field(
        default="medium",
        description="Aggregated volume: high, medium, low"
    )
    competition_tier: str = Field(
        default="medium",
        description="Competition level: high, medium, low"
    )
    
    # Page recommendations
    recommended_page_type: PageType = Field(..., description="Best page type for this cluster")
    recommended_url_slug: Optional[str] = Field(
        None, 
        description="Suggested URL slug for new pages (e.g., '/rural-land-investment/')"
    )
    is_new_page_required: bool = Field(
        default=False,
        description="True if no existing page can target this cluster"
    )
    
    # AEO/GEO optimizations
    answer_format: AnswerFormat = Field(
        ...,
        description="Best content format: paragraph, list, FAQ, table, step-by-step, etc."
    )
    answer_surface_targets: List[AnswerSurface] = Field(
        default_factory=list,
        description="AI/serp features to target: featured_snippet, voice, ai_overview, etc."
    )
    
    # Priority and scoring
    priority_score: int = Field(
        default=50,
        ge=0,
        le=100,
        description="Cluster priority score 0-100 based on volume, competition, and citation value"
    )
    cannibalization_risk: Optional[float] = Field(
        None,
        description="Risk score 0-1 if cluster maps to existing page (higher = more risk)"
    )
    
    # SEO metadata
    search_volume_tier: str = Field(
        default="medium",
        description="Relative search volume tier"
    )
    geographic_relevance: Optional[str] = Field(
        None,
        description="Geographic modifier if applicable (e.g., 'Texas', 'national')"
    )
    
    # Internal linking
    internal_link_priority: Optional[str] = Field(
        None,
        description="How this cluster links to others: 'hub', 'spoke', or None"
    )
    
    # Answer engine optimization
    recommended_heading_structure: Optional[str] = Field(
        None,
        description="Suggested H2/H3 structure for this cluster's page"
    )
    target_answer_length: Optional[str] = Field(
        None,
        description="Recommended answer length: 'short (50-100 words)', 'medium (200-500)', 'long (1000+)'"
    )
    
    class Config:
        use_enum_values = True


class KeywordClustersSchema(BaseModel):
    """Complete keyword clustering output with summary statistics."""
    total_clusters: int = Field(..., description="Total number of clusters created")
    total_keywords_clustered: int = Field(
        default=0,
        description="Count of all keywords assigned to clusters"
    )
    
    clusters: List[KeywordCluster] = Field(
        default_factory=list,
        description="List of all keyword clusters"
    )
    
    # Summary statistics
    clusters_by_intent: dict = Field(
        default_factory=dict,
        description="Count of clusters per intent type"
    )
    clusters_by_page_type: dict = Field(
        default_factory=dict,
        description="Count of clusters per recommended page type"
    )
    new_pages_needed: int = Field(
        default=0,
        description="Count of clusters requiring new pages"
    )
    high_priority_clusters: int = Field(
        default=0,
        description="Count of clusters with priority_score >= 80"
    )
    
    # AEO/GEO summary
    featured_snippet_candidates: int = Field(
        default=0,
        description="Clusters targeting featured snippets"
    )
    voice_search_candidates: int = Field(
        default=0,
        description="Clusters optimized for voice search"
    )
    ai_overview_candidates: int = Field(
        default=0,
        description="Clusters targeting AI Overviews"
    )
    
    # Cluster relationships
    hub_clusters: List[str] = Field(
        default_factory=list,
        description="Cluster IDs identified as hub pages for internal linking"
    )
    spoke_clusters: List[str] = Field(
        default_factory=list,
        description="Cluster IDs that should link to hub pages"
    )


__all__ = [
    "ClusterIntent",
    "PageType",
    "AnswerFormat",
    "AnswerSurface",
    "KeywordCluster",
    "KeywordClustersSchema",
]
