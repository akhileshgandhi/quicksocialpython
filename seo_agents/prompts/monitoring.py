"""
Monitoring prompt templates for Agent 14.
"""

from typing import Any, Dict, Optional


def build_monitoring_prompt(
    site_inventory: Dict[str, Any],
    page_keyword_map: Dict[str, Any],
    seo_priority_backlog: Dict[str, Any],
    previous_dashboard: Optional[Dict[str, Any]],
) -> str:
    """Build prompt for performance monitoring and re-optimization."""
    prev_str = str(previous_dashboard)[:1000] if previous_dashboard else "No previous dashboard"

    return f"""You are an SEO monitoring agent. Analyze current performance vs baseline and identify decay.

Site Inventory (current state):
{str(site_inventory)[:2000]}

Page-Keyword Map:
{str(page_keyword_map)[:2000]}

SEO Priority Backlog:
{str(seo_priority_backlog)[:1000]}

Previous Dashboard:
{prev_str}

For each tracked page, compare:
- Current metadata vs optimization briefs
- Implementation status (implemented, partial, not_started)
- Trend (improving, stable, declining)

Provide a JSON object:
{{
    "performance_dashboard": {{
        "snapshot_date": "<ISO date>",
        "total_pages_tracked": <integer>,
        "pages": [
            {{
                "url": "<URL>",
                "target_keyword": "<keyword>",
                "current_title": "<title>",
                "current_word_count": <integer>,
                "response_time_ms": <integer>,
                "implementation_status": "<implemented|partial|not_started>",
                "trend": "<improving|stable|declining>"
            }}
        ],
        "overall_trend": "<improving|stable|declining>",
        "summary": "<LLM-generated narrative>"
    }},
    "reoptimization_queue": {{
        "total_items": <integer>,
        "items": [
            {{
                "url": "<URL>",
                "target_keyword": "<keyword>",
                "reason": "<why re-optimization needed>",
                "suggested_action": "<update_content|refresh_meta|add_internal_links>",
                "priority": "<high|medium|low>"
            }}
        ]
    }}
}}

Return ONLY valid JSON without any additional text."""