"""Pydantic schema for keyword clusters."""
from typing import List
from pydantic import BaseModel


class KeywordCluster(BaseModel):
    cluster_id: str  # e.g., "cluster_001"
    cluster_name: str
    primary_keyword: str
    supporting_keywords: List[str]
    intent: str
    total_volume_tier: str  # "high", "medium", "low"
    recommended_page_type: str  # "blog_post", "landing_page", "product_page", "category_page"


class KeywordClustersSchema(BaseModel):
    total_clusters: int
    clusters: List[KeywordCluster]
