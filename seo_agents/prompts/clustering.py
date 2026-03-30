"""
Keyword clustering prompt templates for Agent 05 (ClusteringAgent).

Groups semantically related keywords into intent-aligned clusters with AEO/GEO optimizations.
"""

from typing import Any, Dict, Optional


def build_clustering_prompt(
    keyword_universe: Dict[str, Any],
    project_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build comprehensive prompt for keyword clustering.
    
    Args:
        keyword_universe: Full keyword universe from Agent 04 with keywords, intent, volume tiers
        project_context: Optional project context from Agent 01 for naming context
        
    Returns:
        Formatted prompt string for the LLM
    """
    # Extract keywords from universe
    keywords = keyword_universe.get("keywords", [])
    
    # Get project context for naming hints
    context_info = ""
    if project_context:
        business_name = project_context.get("business_name", "")
        industry = project_context.get("industry", "")
        context_info = f"""
BUSINESS CONTEXT:
- Business: {business_name}
- Industry: {industry}
"""
    
    # Format keywords for the prompt
    keywords_text = _format_keywords_for_prompt(keywords)
    
    return f"""You are an SEO keyword clustering specialist. Your task is to group semantically related keywords into clusters that each represent a single topic for one webpage.

{context_info}

## CLUSTERING RULES:

1. **One Topic Per Cluster**: Each cluster must represent ONE distinct topic/theme
2. **One Primary Keyword**: Each cluster has exactly ONE primary keyword (highest value)
3. **Semantic Grouping**: Group keywords by meaning, not just exact match
4. **No Overlap > 40%**: No two clusters should have more than 40% keyword overlap
5. **Question Keywords**: Preserve question-format and conversational variants when they indicate answer-engine opportunities (featured snippets, voice search)
6. **Intent Consistency**: All keywords in a cluster should share the same dominant intent

## KEYWORD UNIVERSE:

{keywords_text}

## OUTPUT SCHEMA:

Return a JSON object with this structure:
{{
    "total_clusters": <integer - total number of clusters created>,
    "clusters": [
        {{
            "cluster_id": "<cluster_001>",
            "cluster_name": "<descriptive name for this cluster topic>",
            
            "primary_keyword": "<main target keyword>",
            "supporting_keywords": ["list", "of", "related", "keywords"],
            
            "intent": "<informational|navigational|commercial|transactional>",
            "funnel_stage": "<TOFU|MOFU|BOFU>",
            
            "total_volume_tier": "<high|medium|low>",
            "competition_tier": "<high|medium|low>",
            
            "recommended_page_type": "<blog_post|landing_page|product_page|category_page|faq_page|how_to_guide>",
            "recommended_url_slug": "<suggested URL slug for new pages, e.g., '/rural-land-investment/'>",
            "is_new_page_required": <true|false>,
            
            "answer_format": "<short_paragraph|list|faq|table|step_by_step|comparison|definition|tutorial>",
            "answer_surface_targets": ["<featured_snippet|voice_search|ai_overview|people_also_ask>", ...],
            
            "priority_score": <0-100 integer>,
            "cannibalization_risk": <0-1 float or null>,
            
            "search_volume_tier": "<high|medium|low>",
            "geographic_relevance": "<optional geographic modifier>",
            
            "internal_link_priority": "<hub|spoke|null>",
            "recommended_heading_structure": "<suggested H2/H3 structure>",
            "target_answer_length": "<short (50-100 words)|medium (200-500)|long (1000+)>"
        }}
    ]
}}

## CLUSTERING GUIDELINES:

### Intent Classification:
- **Informational**: User seeks knowledge (how to, what is, tutorials)
- **Navigational**: User seeks specific site/page (brand names)
- **Commercial**: User researches before purchase (best X, X vs Y)
- **Transactional**: User ready to buy (buy X, X for sale)

### Funnel Stage Assignment:
- **TOFU** (Top of Funnel): Awareness, broad informational queries
- **MOFU** (Middle of Funnel): Consideration, comparing options
- **BOFU** (Bottom of Funnel): Decision, specific product/service queries

### Answer Format Selection:
- **short_paragraph**: Definition-style, 50-100 word answers
- **list**: Numbered or bulleted items
- **faq**: Question-answer pairs
- **table**: Comparison data
- **step_by_step**: How-to processes
- **comparison**: Side-by-side comparisons
- **definition**: Explain a concept
- **tutorial**: Long-form educational content

### Answer Surface Targets:
- **featured_snippet**: Direct answer boxes in SERPs
- **voice_search**: Alexa/Siri/Google Assistant queries
- **ai_overview**: Google's AI-generated summaries
- **people_also_ask**: Expandable question boxes

### Internal Linking (Hub/Spoke Model):
- **hub**: High-level topic pages that link to many others
- **spoke**: Specific topic pages that link to hub pages
- Assign 2-4 hub clusters based on broadest topics

### Priority Scoring (0-100):
Consider: search volume, competition level, business relevance, AEO potential
- 80-100: High priority, high volume, good competition ratio
- 50-79: Medium priority, moderate opportunity
- 0-49: Lower priority, niche or low volume

## REQUIREMENTS:

1. Cluster ALL keywords - each must appear in exactly one cluster
2. Include at least 2 supporting keywords per cluster (can be just the primary if no others naturally fit)
3. Target 5-15 clusters depending on keyword diversity
4. Mark clusters as `is_new_page_required: true` only if NO existing page can target them
5. Identify hub clusters (2-4) for internal linking strategy
6. Preserve question-format keywords for AEO targeting
7. Assign `cannibalization_risk` only if cluster might compete with existing pages

Return ONLY valid JSON without any additional text or explanation."""


def _format_keywords_for_prompt(keywords: list) -> str:
    """Format keyword list for prompt readability.
    
    Args:
        keywords: List of keyword entries from keyword_universe
        
    Returns:
        Formatted string with keyword details
    """
    if not keywords:
        return "No keywords provided."
    
    # Limit to prevent token overflow (keep most important)
    # Sort by priority_score if available, otherwise by order
    sorted_keywords = sorted(
        keywords,
        key=lambda k: k.get("priority_score", k.get("citation_value_score", 0)),
        reverse=True
    )[:100]  # Limit to 100 keywords for prompt
    
    lines = []
    for i, kw in enumerate(sorted_keywords, 1):
        keyword = kw.get("keyword", "unknown")
        intent = kw.get("intent", "unknown")
        volume = kw.get("volume_tier", "unknown")
        surfaces = kw.get("answer_surfaces", [])
        
        # Include answer surfaces if present
        surface_str = ""
        if surfaces:
            surface_str = f" (targets: {', '.join(surfaces) if isinstance(surfaces, list) else surfaces})"
        
        lines.append(f"{i}. {keyword} | intent: {intent} | volume: {volume}{surface_str}")
    
    return "\n".join(lines)