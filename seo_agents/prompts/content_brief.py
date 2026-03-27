"""
Content brief prompt templates for Agent 11.
"""

from typing import Any, Dict


def build_content_brief_prompt(
    seo_priority_backlog: Dict[str, Any],
    content_gap_report: Dict[str, Any],
    keyword_clusters: Dict[str, Any],
    seo_project_context: Dict[str, Any],
) -> str:
    """Build prompt for content brief generation."""
    return f"""You are a content planning agent. Generate detailed content briefs for new content items.

SEO Priority Backlog (new_content items):
{str(seo_priority_backlog)[:2000]}

Content Gap Report:
{str(content_gap_report)[:2000]}

Keyword Clusters:
{str(keyword_clusters)[:2000]}

Brand Voice: {seo_project_context.get('brand_voice', 'professional')}

For each content item, generate:
- Recommended title and URL slug
- Target word count range
- Detailed outline (H2/H3 structure)
- Tone and style guidance
- Internal linking targets
- Call-to-action suggestions

Provide a JSON object:
{{
    "total_briefs": <integer>,
    "briefs": [
        {{
            "cluster_id": "<cluster ID>",
            "target_keyword": "<keyword>",
            "recommended_title": "<title>",
            "recommended_slug": "<URL slug>",
            "content_type": "<blog_post|guide|comparison|FAQ|etc>",
            "target_word_count_min": <integer>,
            "target_word_count_max": <integer>,
            "outline": [
                {{
                    "heading": "<heading text>",
                    "level": <2 or 3>,
                    "key_points": ["list", "of", "points"],
                    "supporting_keywords": ["list", "of", "keywords"]
                }}
            ],
            "tone_guidance": "<tone description>",
            "internal_links": [
                {{"anchor_text": "<text>", "target_url": "<URL>"}}
            ],
            "cta_suggestions": ["list", "of", "CTAs"]
        }}
    ]
}}

Return ONLY valid JSON without any additional text."""