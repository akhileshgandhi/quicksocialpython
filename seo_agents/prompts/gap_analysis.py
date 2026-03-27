"""
Gap analysis prompt templates for Agent 08.
"""

from typing import Any, Dict


def build_gap_analysis_prompt(
    page_keyword_map: Dict[str, Any],
    competitor_matrix: Dict[str, Any],
    keyword_clusters: Dict[str, Any],
) -> str:
    """Build prompt for content gap analysis."""
    return f"""You are an SEO gap analysis agent. Identify content gaps vs competitors.

Page-Keyword Map:
{str(page_keyword_map)[:3000]}

Competitor Matrix:
{str(competitor_matrix)[:2000]}

Keyword Clusters:
{str(keyword_clusters)[:2000]}

Identify clusters where assignment="new_page" and cross-reference with competitor gap opportunities.
Prioritize by business impact and suggest content types.

Provide a JSON object:
{{
    "total_gaps": <integer>,
    "gaps": [
        {{
            "cluster_id": "<cluster ID>",
            "primary_keyword": "<keyword>",
            "priority": "<high|medium|low>",
            "suggested_content_type": "<blog_post|guide|comparison|FAQ|etc>",
            "effort_level": "<quick_win|moderate|deep_investment>",
            "competitor_coverage": "<how many competitors cover this>",
            "rationale": "<explanation>"
        }}
    ],
    "quick_wins": ["list", "of", "cluster", "IDs"]
}}

Return ONLY valid JSON without any additional text."""