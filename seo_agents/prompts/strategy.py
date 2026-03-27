"""
Strategy prompt templates for Agent 09.
"""

from typing import Any, Dict


def build_strategy_prompt(
    technical_audit_report: Dict[str, Any],
    content_gap_report: Dict[str, Any],
    page_keyword_map: Dict[str, Any],
    seo_project_context: Dict[str, Any],
) -> str:
    """Build prompt for SEO strategy and prioritization."""
    return f"""You are an SEO strategy agent. Create a prioritized backlog based on impact vs effort.

Technical Audit Report:
{str(technical_audit_report)[:2000]}

Content Gap Report:
{str(content_gap_report)[:2000]}

Page-Keyword Map:
{str(page_keyword_map)[:2000]}

Business Goals:
{str(seo_project_context.get('primary_goals', []))}

Aggregate all actionable items: technical fixes, page optimizations, new content.
Score on impact-vs-effort matrix, group into phases (month_1, month_2, month_3_plus).

Provide a JSON object:
{{
    "total_items": <integer>,
    "items": [
        {{
            "item_id": "<unique ID>",
            "type": "<technical_fix|page_optimization|new_content>",
            "title": "<title>",
            "description": "<description>",
            "target_keyword": "<keyword or null>",
            "target_url": "<URL or null>",
            "impact_score": <1-10>,
            "effort_score": <1-10>,
            "priority_rank": <integer>,
            "phase": "<month_1|month_2|month_3_plus>"
        }}
    ],
    "summary": "<LLM-generated executive summary>"
}}

Return ONLY valid JSON without any additional text."""