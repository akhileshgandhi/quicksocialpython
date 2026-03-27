"""
Keyword research prompt templates for Agent 05.
"""

from typing import Any, Dict


def build_keyword_research_prompt(
    seo_project_context: Dict[str, Any],
    site_inventory: Dict[str, Any],
    competitor_matrix: Dict[str, Any],
) -> str:
    """Build prompt for keyword research."""
    industry = seo_project_context.get("industry", "")
    target_audience = seo_project_context.get("target_audience", [])
    products = seo_project_context.get("key_products_services", [])
    gap_opportunities = competitor_matrix.get("gap_opportunities", [])

    return f"""You are an SEO keyword researcher. Expand seed terms and classify keywords.

Industry: {industry}
Target Audience: {target_audience}
Products/Services: {products}
Competitor Gap Keywords: {gap_opportunities}

Site Page Titles (for seed terms):
{str([p.get('title') for p in site_inventory.get('pages', [])[:20]])}

Expand each seed term into long-tail variations, classify:
- Intent: informational, navigational, commercial, transactional
- Volume tier: high, medium, low
- Competition tier: high, medium, low
- Source: seed, expansion, competitor_gap

Provide a JSON object:
{{
    "total_keywords": <integer>,
    "keywords": [
        {{
            "keyword": "<keyword phrase>",
            "intent": "<informational|navigational|commercial|transactional>",
            "volume_tier": "<high|medium|low>",
            "competition_tier": "<high|medium|low>",
            "source": "<seed|expansion|competitor_gap>"
        }}
    ],
    "seed_terms_used": ["list", "of", "seed", "terms"]
}}

Return ONLY valid JSON without any additional text."""