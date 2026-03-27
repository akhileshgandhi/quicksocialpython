"""
Crawl prompt templates for Agent 02.
"""

from typing import Any, Dict


def build_crawl_prompt(website_url: str, crawl_depth: int, max_pages: int) -> str:
    """Build prompt for site crawl inventory."""
    return f"""You are an SEO crawling agent. Perform a breadth-first crawl of the website and create an inventory.

Website URL: {website_url}
Crawl Depth: {crawl_depth}
Max Pages: {max_pages}

Analyze the website structure and provide a JSON object with this structure:
{{
    "total_pages": <integer>,
    "crawl_depth_reached": <integer>,
    "pages": [
        {{
            "url": "<page URL>",
            "status_code": <integer>,
            "title": "<title tag content or null>",
            "meta_description": "<meta description or null>",
            "h1": "<H1 heading or null>",
            "word_count": <integer>,
            "response_time_ms": <integer>,
            "internal_links": ["list", "of", "internal", "URLs"],
            "external_links": ["list", "of", "external", "URLs"]
        }}
    ],
    "crawl_errors": [
        {{
            "url": "<failed URL>",
            "error": "<error message>"
        }}
    ]
}}

Return ONLY valid JSON without any additional text."""