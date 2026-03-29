"""
Competitor analysis prompt templates for Agent 08.
"""

from typing import Any, Dict


def build_competitor_prompt(
    seo_project_context: Dict[str, Any],
    site_inventory: Dict[str, Any],
) -> str:
    """Build prompt for competitor analysis."""
    competitors = seo_project_context.get("competitors", [])
    industry = seo_project_context.get("industry", "unknown")

    return f"""You are a competitive intelligence analyst. Analyze competitors and create a comparative matrix.

Industry: {industry}
Known Competitors: {competitors}

Site Inventory (for baseline):
{str(site_inventory)[:2000]}

For each competitor (up to 5), perform analysis and provide:
- Estimated page count
- Content themes
- Strengths and weaknesses

Provide a JSON object:
{{
    "competitors": [
        {{
            "name": "<competitor name>",
            "url": "<competitor URL>",
            "estimated_pages": <integer>,
            "content_themes": ["list", "of", "themes"],
            "strengths": ["list", "of", "strengths"],
            "weaknesses": ["list", "of", "weaknesses"]
        }}
    ],
    "overlap_keywords": ["keywords", "both", "target"],
    "gap_opportunities": ["keywords", "competitors", "rank", "for", "but", "not", "you"],
    "competitive_position": "<LLM-generated narrative summary>"
}}

Return ONLY valid JSON without any additional text."""