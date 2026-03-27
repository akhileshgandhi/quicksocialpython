"""
Page-keyword mapping prompt templates for Agent 07.
"""

from typing import Any, Dict


def build_page_mapping_prompt(
    site_inventory: Dict[str, Any],
    keyword_clusters: Dict[str, Any],
) -> str:
    """Build prompt for mapping clusters to pages."""
    return f"""You are an SEO page mapping agent. Map keyword clusters to existing pages or identify new pages needed.

Site Inventory (existing pages):
{str(site_inventory)[:3000]}

Keyword Clusters:
{str(keyword_clusters)[:3000]}

For each cluster, determine the best matching existing page or if a new page is needed.
Assignment types: "existing_page", "new_page", "merge"

Provide a JSON object:
{{
    "mappings": [
        {{
            "cluster_id": "<cluster ID>",
            "primary_keyword": "<primary keyword>",
            "assignment": "<existing_page|new_page|merge>",
            "existing_page_url": "<URL or null>",
            "merge_into_cluster_id": "<cluster ID or null>",
            "recommended_url_slug": "<slug for new pages or null>",
            "recommended_page_type": "<page type>"
        }}
    ],
    "total_existing_matches": <integer>,
    "total_new_pages_needed": <integer>,
    "total_merges": <integer>
}}

Return ONLY valid JSON without any additional text."""