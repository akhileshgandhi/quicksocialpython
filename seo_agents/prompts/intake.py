"""
Intake prompt templates for Agent 01.
"""

from typing import Any, Dict, Optional


def build_intake_prompt(
    website_url: str,
    brand_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Build prompt for synthesizing form inputs into structured business context."""
    return f"""You are an SEO intake assistant. Analyze the provided website and business information to create a structured business context object.

Website URL: {website_url}
Brand ID: {brand_id or "Not provided"}

Configuration:
- Target Geography: {config.get("target_geography", "Global") if config else "Global"}
- Crawl Depth: {config.get("crawl_depth", 3) if config else 3}

Analyze the website and provide a JSON object with these fields:
{{
    "business_name": "The business name found on the website",
    "website_url": "{website_url}",
    "industry": "The industry/niche the business operates in",
    "target_audience": ["list", "of", "target", "audiences"],
    "primary_goals": ["list", "of", "primary", "business", "goals"],
    "geographic_focus": "The geographic focus of the business",
    "competitors": ["list", "of", "known", "competitors", "or", "empty"],
    "brand_voice": "Description of brand voice/tone if inferable",
    "key_products_services": ["list", "of", "key", "products", "or", "services"]
}}

Return ONLY valid JSON without any additional text."""