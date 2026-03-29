"""
Keyword research prompt templates for Agent 04.

IMPORTANT: In the new architecture, Agent 08 (Competitor) runs AFTER Agent 04.
So competitor_matrix is NOT available as input to this agent.

Input Requirements:
- seo_project_context: industry, target_audience, key_products_services
- site_inventory: existing page titles and content themes

Output includes AEO/GEO enhancements:
- query_format: keyword, question, conversational, voice
- answer_surfaces: featured_snippet, voice_assistant, ai_overview, ai_chat
- citation_value_score: 1-10
"""

from typing import Any, Dict, List

# Default number of pages to extract for seed terms
DEFAULT_PAGE_LIMIT = 30


def build_keyword_research_prompt(
    seo_project_context: Dict[str, Any],
    site_inventory: Dict[str, Any],
    page_limit: int = DEFAULT_PAGE_LIMIT,
) -> str:
    """Build prompt for keyword research.
    
    Args:
        seo_project_context: Business context from Agent 01
        site_inventory: Website pages from Agent 02
        page_limit: Maximum number of pages to extract for seed terms (default: 30)
        
    Returns:
        Formatted prompt string for Gemini
    """
    industry = seo_project_context.get("industry", "")
    target_audience = seo_project_context.get("target_audience", [])
    products = seo_project_context.get("key_products_services", [])
    geographic_focus = seo_project_context.get("geographic_focus", "Global")
    
    # Extract page titles and H1s from site inventory for seed terms
    # Handle both dict and Pydantic model inputs
    if hasattr(site_inventory, 'model_dump'):
        # It's a Pydantic model, convert to dict
        inv_dict = site_inventory.model_dump()
    else:
        inv_dict = site_inventory
    
    pages = inv_dict.get("pages", [])
    page_titles = []
    page_h1s = []
    for p in pages[:page_limit]:
        # Handle both dict and Pydantic objects
        if hasattr(p, 'model_dump'):
            # Pydantic model
            title = getattr(p, 'title', None)
            h1 = getattr(p, 'h1', None)
        elif isinstance(p, dict):
            title = p.get("title")
            h1 = p.get("h1")
        else:
            title = None
            h1 = None
        
        if title:
            page_titles.append(title)
        if h1:
            page_h1s.append(h1)
    
    return f"""You are an SEO keyword researcher specializing in both traditional SEO and AI-powered search (AEO/GEO).

Your task is to generate a comprehensive keyword universe for a business website.

## Business Context
- Industry: {industry}
- Target Audience: {target_audience}
- Products/Services: {products}
- Geographic Focus: {geographic_focus}

## Existing Website Pages (use titles/H1s as seed terms)
Page Titles: {page_titles}
Page H1s: {page_h1s}

## Your Task
1. Create seed terms from the products/services and page titles
2. Expand each seed term into long-tail variations
3. Generate question-based, conversational, and voice-search variants
4. Classify each keyword with the following attributes:

### Classification Required
- **intent**: informational | navigational | commercial | transactional
- **volume_tier**: high | medium | low (relative, not absolute)
- **competition_tier**: high | medium | low (relative to industry)
- **source**: seed | site_inventory | expansion | question_variant
- **query_format**: keyword | question | conversational | voice
- **answer_surfaces**: (array) featured_snippet | voice_assistant | ai_overview | ai_chat
- **citation_value_score**: 1-10 (how valuable for AI citation - higher = more authoritative source potential)

## AEO/GEO Requirements
For each keyword, determine if it's suitable for:
- **Featured Snippet**: Questions starting with What, How, Why, When, Where
- **Voice Search**: Conversational, natural language phrases
- **AI Overview**: Informational queries with clear factual answers
- **AI Chat**: Complex questions requiring detailed responses

Assign higher citation_value_score (8-10) to keywords where:
- The business can provide authoritative, factual answers
- The topic requires expertise/experience
- There's opportunity to be cited as a source

## Output Format
Return ONLY valid JSON with this structure:
{{
    "total_keywords": <integer>,
    "keywords": [
        {{
            "keyword": "<keyword phrase>",
            "intent": "<informational|navigational|commercial|transactional>",
            "volume_tier": "<high|medium|low>",
            "competition_tier": "<high|medium|low>",
            "source": "<seed|site_inventory|expansion|question_variant>",
            "query_format": "<keyword|question|conversational|voice>",
            "answer_surfaces": ["<featured_snippet|voice_assistant|ai_overview|ai_chat>"],
            "citation_value_score": <1-10>
        }}
    ],
    "seed_terms_used": ["list", "of", "seed", "terms"],
    "featured_snippet_opportunities": <count>,
    "voice_search_opportunities": <count>,
    "ai_overview_opportunities": <count>,
    "high_citation_value_keywords": <count>
}}

Return ONLY valid JSON without any additional text."""
