"""
On-page optimization prompt templates for Agent 10.
"""

from typing import Any, Dict


def build_on_page_prompt(
    seo_priority_backlog: Dict[str, Any],
    site_inventory: Dict[str, Any],
    page_keyword_map: Dict[str, Any],
) -> str:
    """Build prompt for on-page optimization briefs."""
    return f"""You are an on-page SEO optimization agent. Generate optimization briefs for existing pages.

SEO Priority Backlog (page_optimization items):
{str(seo_priority_backlog)[:2000]}

Site Inventory:
{str(site_inventory)[:2000]}

Page-Keyword Map:
{str(page_keyword_map)[:2000]}

For each optimization item, generate:
- Recommended title tag (with target keyword)
- Recommended meta description
- Recommended H1
- Recommended header structure (H2s, H3s)
- Internal linking suggestions
- Image alt text suggestions

Provide a JSON object:
{{
    "total_briefs": <integer>,
    "briefs": [
        {{
            "target_url": "<URL>",
            "target_keyword": "<keyword>",
            "recommended_title": "<title tag>",
            "recommended_meta_description": "<meta description>",
            "recommended_h1": "<H1 heading>",
            "recommended_headers": [
                {{"level": "h2", "text": "<header text>"}},
                {{"level": "h3", "text": "<header text>"}}
            ],
            "internal_link_suggestions": [
                {{"anchor_text": "<text>", "target_url": "<URL>"}}
            ],
            "image_alt_suggestions": ["list", "of", "suggestions"]
        }}
    ]
}}

Return ONLY valid JSON without any additional text."""