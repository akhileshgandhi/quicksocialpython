"""
Intake prompt templates for Agent 01.

These prompts synthesize raw user form inputs into a structured business context
object that downstream agents can use for SEO analysis.
"""

from typing import Any, Dict, Optional


SYSTEM_PROMPT = """You are an expert SEO business analyst. Your task is to analyze 
the provided website information and create a structured business context object.

Be thorough and infer as much as possible from the website URL. If information is 
not available, use reasonable defaults based on the industry.

Return ONLY valid JSON without any additional text, markdown, or explanations."""


USER_PROMPT_TEMPLATE = """Analyze the following business information and create a 
structured business context object for SEO optimization.

## Website Information
- Website URL: {website_url}
- Brand ID: {brand_id}

## Configuration
- Target Geography: {target_geography}
- Crawl Depth: {crawl_depth}

## Required JSON Output
Provide a JSON object with these exact fields:

{{
    "business_name": "The official business name (infer from URL if not provided)",
    "website_url": "{website_url}",
    "industry": "The industry/niche (e.g., 'Healthcare', 'E-commerce', 'SaaS')",
    "target_audience": [
        "List of 2-5 target audience segments based on the business type"
    ],
    "primary_goals": [
        "List of 2-5 primary business goals for SEO (e.g., 'increase traffic', 'generate leads')"
    ],
    "geographic_focus": "{target_geography}",
    "competitors": [
        "List of known competitors or empty array if none known"
    ],
    "brand_voice": "Description of brand voice/tone (e.g., 'Professional, authoritative' or 'Friendly, casual')",
    "key_products_services": [
        "List of 3-10 key products or services offered"
    ]
}}

Ensure all arrays have at least 2 items unless explicitly empty. Use realistic 
inferences based on common business patterns for the industry."""


def build_intake_prompt(
    website_url: str,
    brand_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the full prompt for intake agent."""
    target_geography = config.get("target_geography", "Global") if config else "Global"
    crawl_depth = config.get("crawl_depth", 3) if config else 3
    
    return f"{SYSTEM_PROMPT}\n\n{USER_PROMPT_TEMPLATE}".format(
        website_url=website_url,
        brand_id=brand_id or "Not provided",
        target_geography=target_geography,
        crawl_depth=crawl_depth,
    )


def build_intake_prompt_with_form_data(
    website_url: str,
    business_name: Optional[str] = None,
    industry: Optional[str] = None,
    target_audience: Optional[list] = None,
    primary_goals: Optional[list] = None,
    competitors: Optional[list] = None,
    brand_voice: Optional[str] = None,
    key_products_services: Optional[list] = None,
    brand_id: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """Build intake prompt with pre-provided form data (optional enhancement)."""
    target_geography = config.get("target_geography", "Global") if config else "Global"
    crawl_depth = config.get("crawl_depth", 3) if config else 3
    
    user_provided = []
    if business_name:
        user_provided.append(f"- Business Name: {business_name}")
    if industry:
        user_provided.append(f"- Industry: {industry}")
    if target_audience:
        user_provided.append(f"- Target Audience: {', '.join(target_audience)}")
    if primary_goals:
        user_provided.append(f"- Primary Goals: {', '.join(primary_goals)}")
    if competitors:
        user_provided.append(f"- Competitors: {', '.join(competitors)}")
    if brand_voice:
        user_provided.append(f"- Brand Voice: {brand_voice}")
    if key_products_services:
        user_provided.append(f"- Products/Services: {', '.join(key_products_services)}")
    
    user_data_section = "\n".join(user_provided) if user_provided else "No additional form data provided."
    
    return f"""{SYSTEM_PROMPT}

The user has provided the following information. Use this to enhance your analysis:

{user_data_section}

## Website Information
- Website URL: {website_url}
- Brand ID: {brand_id or "Not provided"}

## Configuration
- Target Geography: {target_geography}
- Crawl Depth: {crawl_depth}

Return ONLY valid JSON with these fields:

{{
    "business_name": "The business name",
    "website_url": "{website_url}",
    "industry": "The industry/niche",
    "target_audience": ["list of target audiences"],
    "primary_goals": ["list of business goals"],
    "geographic_focus": "{target_geography}",
    "competitors": ["list of competitors or empty"],
    "brand_voice": "Description of brand voice",
    "key_products_services": ["list of products/services"]
}}"""