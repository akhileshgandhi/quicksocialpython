"""
Crawl prompt templates for Agent 02.

This module contains prompt templates used by the CrawlAgent to generate
comprehensive SEO site inventories via LLM calls.
"""

from typing import Any, Dict


def build_crawl_prompt(website_url: str, crawl_depth: int, max_pages: int) -> str:
    """Build a comprehensive prompt for SEO site crawl.
    
    This prompt instructs the LLM to perform a breadth-first crawl
    and collect detailed SEO metadata for each page.
    
    Args:
        website_url: Root URL to crawl
        crawl_depth: Maximum depth for BFS crawl
        max_pages: Maximum number of pages to crawl
        
    Returns:
        Prompt string for LLM
    """
    return f"""You are an expert SEO crawling agent. Perform a breadth-first crawl 
of {website_url} and create a detailed inventory for SEO analysis.

Crawl Depth: {crawl_depth}, Max Pages: {max_pages}

Return a JSON object with this structure:
{{
    "total_pages": <int>,
    "crawl_depth_reached": <int>,
    "pages": [
        {{
            "url": "<url>",
            "status_code": <int>,
            "title": "<title or null>",
            "meta_description": "<meta desc or null>",
            "h1": "<H1 or null>",
            "h2_tags": ["H2 headings"],
            "h3_tags": ["H3 headings"],
            "canonical_url": "<canonical or null>",
            "is_https": <true/false>,
            "robots_directive": "<index/noindex/etc or null>",
            "og_title": "<og:title or null>",
            "og_description": "<og:description or null>",
            "og_image": "<og:image url or null>",
            "schema_markup": "<json-ld or null>",
            "schema_types": ["SchemaType"],
            "word_count": <int>,
            "response_time_ms": <int>,
            "images": [{{"src": "<img>", "alt": "<alt>", "is_optimized": <bool>}}],
            "has_unoptimized_images": <bool>,
            "internal_links": ["urls"],
            "external_links": ["urls"]
        }}
    ],
    "crawl_errors": [{{"url": "<url>", "error": "<msg>"}}],
    "sitemap": {{"found": <bool>, "url": "<url>", "pages_count": <int>}},
    "robots_txt": {{"found": <bool>, "url": "<url>", "allows_crawl": <bool>}},
    "is_https_only": <bool>,
    "has_ssl_issues": <bool>,
    "duplicate_titles": [{{"url": "<url>", "title": "<title>"}}],
    "duplicate_meta_descriptions": [{{"url": "<url>", "meta_description": "<desc>"}}],
    "thin_content_pages": [{{"url": "<url>", "word_count": <int>}}],
    "pages_with_h1": <int>,
    "pages_with_meta_description": <int>,
    "pages_with_schema": <int>,
    "pages_with_og_tags": <int>,
    "avg_response_time_ms": <float>
}}

Include:
- Page titles and meta descriptions
- All heading tags (h1, h2, h3)
- Canonical URLs
- Open Graph meta tags
- Schema.org JSON-LD markup
- Image optimization status
- Internal and external links
- Sitemap.xml and robots.txt detection
- Duplicate content analysis
- Thin content detection
- Response time metrics

Return ONLY valid JSON."""
