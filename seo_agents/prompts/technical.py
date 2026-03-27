"""
Technical audit prompt templates for Agent 03.
"""

from typing import Any, Dict


def build_technical_audit_prompt(site_inventory: Dict[str, Any]) -> str:
    """Build prompt for technical SEO audit."""
    return f"""You are a technical SEO auditor. Analyze the site inventory and identify technical issues.

Site Inventory:
{str(site_inventory)[:5000]}

Analyze each page for:
- Missing or duplicate title tags
- Missing or duplicate meta descriptions
- Missing H1 tags or multiple H1s
- Broken internal links (4xx/5xx status codes)
- Slow response times (> 3 seconds)
- Missing canonical tags
- Non-HTTPS pages

Provide a JSON object:
{{
    "total_issues": <integer>,
    "critical_issues": [
        {{
            "issue_type": "<issue type>",
            "severity": "critical",
            "affected_urls": ["list", "of", "URLs"],
            "description": "<description>",
            "recommendation": "<recommendation>"
        }}
    ],
    "warnings": [
        {{
            "issue_type": "<issue type>",
            "severity": "warning",
            "affected_urls": ["list", "of", "URLs"],
            "description": "<description>",
            "recommendation": "<recommendation>"
        }}
    ],
    "info": [
        {{
            "issue_type": "<issue type>",
            "severity": "info",
            "affected_urls": ["list", "of", "URLs"],
            "description": "<description>",
            "recommendation": "<recommendation>"
        }}
    ],
    "overall_health_score": <integer 0-100>
}}

Return ONLY valid JSON without any additional text."""