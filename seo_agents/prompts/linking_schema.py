"""
Linking & Schema Markup prompt templates for Agent 13.
"""

from typing import Any, Dict, List, Optional


def build_linking_schema_prompt(
    site_inventory: Dict[str, Any],
    page_keyword_map: Dict[str, Any],
    content_drafts: Dict[str, Any],
    seo_project_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build prompt for internal link graph and schema markup generation."""
    
    existing_pages = site_inventory.get("pages", [])[:10]  # Sample for prompt size
    new_pages = content_drafts.get("drafts", [])[:5] if content_drafts else []
    keyword_clusters = page_keyword_map.get("clusters", {})
    business_type = seo_project_context.get("industry", "General") if seo_project_context else "General"
    
    existing_pages_str = "\n".join([
        f"- {p.get('url', 'N/A')}: {p.get('title', 'No Title')}"
        for p in existing_pages
    ])
    
    new_pages_str = "\n".join([
        f"- {p.get('url', 'N/A')}: {p.get('title', 'No Title')} (keyword: {p.get('target_keyword', 'N/A')})"
        for p in new_pages
    ])
    
    return f"""You are an SEO internal linking and schema markup specialist. Analyze the website structure and content to generate:
1. Internal linking recommendations
2. JSON-LD schema markup for key pages

Existing Pages:
{existing_pages_str}

New Content Pages:
{new_pages_str}

Keyword Clusters:
{keyword_clusters}

Business Type: {business_type}

Generate a JSON object with two outputs:

{{
    "internal_link_graph": {{
        "total_links": <number>,
        "links": [
            {{
                "source_url": "url of the page with the link",
                "target_url": "url of the linked page",
                "anchor_text": "recommended anchor text",
                "context": "where in page to place (body_paragraph, sidebar, footer)",
                "priority": "high|medium|low"
            }}
        ],
        "orphan_pages": ["list of pages with no inbound links"],
        "hub_pages": ["list of recommended hub/pillar pages"]
    }},
    "schema_map": {{
        "total_schemas": <number>,
        "schemas": [
            {{
                "page_url": "url",
                "schema_type": "Organization|Article|BlogPosting|Product|FAQPage|LocalBusiness",
                "json_ld": {{"@context": "https://schema.org", "@type": "...", ...}},
                "notes": "implementation notes"
            }}
        ]
    }}
}}

Return ONLY valid JSON without any additional text."""

