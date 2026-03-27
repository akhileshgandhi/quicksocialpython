"""
Content writer prompt templates for Agent 12.
"""

from typing import Any, Dict


def build_content_writer_prompt(
    content_briefs: Dict[str, Any],
    seo_project_context: Dict[str, Any],
) -> str:
    """Build prompt for content draft generation."""
    return f"""You are an SEO content writer. Generate full article drafts based on content briefs.

Content Briefs:
{str(content_briefs)[:4000]}

Brand Voice: {seo_project_context.get('brand_voice', 'professional')}
Target Audience: {seo_project_context.get('target_audience', [])}

For each brief, generate a complete article in Markdown format following the outline.
Include:
- Full article content with proper heading hierarchy
- Keyword placement (natural density 1-2%)
- Internal links where appropriate
- Meta description

Provide a JSON object:
{{
    "total_drafts": <integer>,
    "drafts": [
        {{
            "cluster_id": "<cluster ID>",
            "title": "<article title>",
            "slug": "<URL slug>",
            "content_markdown": "<full article in markdown>",
            "word_count": <integer>,
            "target_keyword": "<keyword>",
            "keyword_density": <float>,
            "meta_description": "<meta description>",
            "status": "draft"
        }}
    ]
}}

Return ONLY valid JSON without any additional text."""