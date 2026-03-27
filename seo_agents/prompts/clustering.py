"""
Keyword clustering prompt templates for Agent 06.
"""

from typing import Any, Dict


def build_clustering_prompt(keyword_universe: Dict[str, Any]) -> str:
    """Build prompt for keyword clustering."""
    return f"""You are an SEO keyword clustering agent. Group semantically related keywords into clusters.

Keyword Universe:
{str(keyword_universe)[:5000]}

Group keywords into clusters where each cluster represents a single topic that could be targeted by one page.
For each cluster provide:
- cluster_id (e.g., "cluster_001")
- cluster_name
- primary_keyword
- supporting_keywords (list)
- intent (based on majority of keywords)
- total_volume_tier (aggregated)
- recommended_page_type (blog_post, landing_page, product_page, category_page)

Provide a JSON object:
{{
    "total_clusters": <integer>,
    "clusters": [
        {{
            "cluster_id": "<cluster_001>",
            "cluster_name": "<descriptive name>",
            "primary_keyword": "<primary keyword>",
            "supporting_keywords": ["list", "of", "keywords"],
            "intent": "<informational|navigational|commercial|transactional>",
            "total_volume_tier": "<high|medium|low>",
            "recommended_page_type": "<blog_post|landing_page|product_page|category_page>"
        }}
    ]
}}

Return ONLY valid JSON without any additional text."""