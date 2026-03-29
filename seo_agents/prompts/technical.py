"""
Technical audit prompt templates for Agent 03 - TechnicalAuditAgent.

IMPORTANT: Agent 02 (CrawlAgent) already performs programmatic detection of:
- Duplicate titles, duplicate meta descriptions, thin content pages
- Pages missing H1, meta descriptions, schema, OG tags
- Page status codes, response times, HTTPS check
- Broken links (4xx/5xx)

Agent 03 focuses EXCLUSIVELY on inference-based analysis that cannot be
programmatically detected. This prompt instructs the LLM to analyze
content quality, semantic relevance, accessibility, and site architecture.

Enhanced with AEO/GEO analysis for Answer Engine Optimization and Generative Engine Optimization.

Input:
    site_inventory: Dict from Agent 02 containing pages with metadata
    seo_project_context: Dict from Agent 01 containing business context

Output:
    JSON with inference-based issues + programmatic summary reference + AEO/GEO scores
"""

from typing import Any, Dict


# Template parts for building the prompt
SYSTEM_CONTEXT = """You are a senior technical SEO auditor specializing in inference-based analysis
AND Answer Engine Optimization (AEO) / Generative Engine Optimization (GEO)."""


AEO_GEO_CONTEXT = """
## AEO/GEO Context (from Intake)
- Voice Search Goals: {voice_search_goals}
- AI Citation Targets: {ai_citation_targets}
- Featured Snippet Targets: {featured_snippet_targets}
- Target AI Platforms: {target_ai_platforms}
- Conversational Content Priority: {conversational_priority}

## AEO/GEO Summary (from crawl)
- Pages with FAQ Schema: {pages_with_faq}
- Pages with Speakable Markup: {pages_with_speakable}
- Pages Eligible for Featured Snippets: {pages_eligible_snippets}
"""


OUTPUT_FORMAT = """
## Output Format
Provide a JSON object with inference-based findings AND AEO/GEO scores:

{
    "total_inference_issues": <integer>,
    "inference_critical": [
        {
            "issue_type": "<content_quality|semantic_mismatch|accessibility|architecture>",
            "severity": "critical",
            "affected_urls": ["list", "of", "URLs"],
            "description": "<LLM-generated description>",
            "recommendation": "<actionable recommendation>"
        }
    ],
    "inference_warnings": [
        {same structure as critical}
    ],
    "inference_info": [
        {same structure as critical}
    ],
    "programmatic_summary": {
        "duplicate_titles_count": <integer>,
        "duplicate_meta_count": <integer>,
        "thin_content_count": <integer>,
        "pages_missing_h1_count": <integer>,
        "pages_missing_meta_count": <integer>,
        "broken_links_count": <integer>
    },
    "overall_health_score": <integer 0-100>,
    
    // AEO/GEO Enhancement fields (new)
    "answer_readiness_score": <integer 0-100>,
    "citation_trust_score": <integer 0-100>,
    "voice_search_readiness": "<excellent|good|needs_improvement|poor>",
    "aeo_recommendations": ["list of AEO-specific recommendations"],
    "geo_recommendations": ["list of GEO-specific recommendations"],
    "schema_quality_for_ai": "<none|basic|good|excellent>"
}

Return ONLY valid JSON without any additional text."""


def build_technical_audit_prompt(
    site_inventory: Dict[str, Any],
    seo_project_context: Dict[str, Any]
) -> str:
    """Build prompt for inference-based technical SEO audit.
    
    This focuses on content quality, semantic analysis, accessibility signals,
    and architecture recommendations that require LLM inference.
    
    Enhanced with AEO/GEO analysis.
    
    Args:
        site_inventory: Complete site inventory from Agent 02
        seo_project_context: Business context from Agent 01
        
    Returns:
        Formatted prompt string for Gemini
    """
    # Extract key info from project context
    business_name = seo_project_context.get("business_name", "the business")
    industry = seo_project_context.get("industry", "unknown")
    target_audience = seo_project_context.get("target_audience", [])
    primary_goals = seo_project_context.get("primary_goals", [])
    
    # AEO/GEO fields from project context
    voice_search_goals = seo_project_context.get("voice_search_goals", [])
    ai_citation_targets = seo_project_context.get("ai_citation_targets", [])
    featured_snippet_targets = seo_project_context.get("featured_snippet_targets", [])
    target_ai_platforms = seo_project_context.get("target_ai_platforms", [])
    conversational_priority = seo_project_context.get("conversational_content_priority", False)
    
    # Extract summary from site inventory (for context)
    total_pages = site_inventory.get("total_pages", 0)
    pages_with_schema = site_inventory.get("pages_with_schema", 0)
    pages_with_h1 = site_inventory.get("pages_with_h1", 0)
    
    # AEO/GEO specific from site inventory
    pages_with_faq = site_inventory.get("pages_with_faq_schema", 0)
    pages_with_speakable = site_inventory.get("pages_with_speakable_markup", 0)
    pages_eligible_snippets = site_inventory.get("pages_eligible_for_featured_snippets", 0)
    
    # Extract programmatic counts for summary
    duplicate_titles = site_inventory.get("duplicate_titles", [])
    duplicate_meta = site_inventory.get("duplicate_meta_descriptions", [])
    thin_content = site_inventory.get("thin_content_pages", [])
    
    # Get sample pages for analysis (limit to 50 for prompt size)
    pages = site_inventory.get("pages", [])[:50]
    
    # Build AEO/GEO context section
    aeo_geo_context = AEO_GEO_CONTEXT.format(
        voice_search_goals=', '.join(voice_search_goals) if voice_search_goals else 'Not specified',
        ai_citation_targets=', '.join(ai_citation_targets) if ai_citation_targets else 'Not specified',
        featured_snippet_targets=', '.join(featured_snippet_targets) if featured_snippet_targets else 'Not specified',
        target_ai_platforms=', '.join(target_ai_platforms) if target_ai_platforms else 'General AI',
        conversational_priority=conversational_priority,
        pages_with_faq=pages_with_faq,
        pages_with_speakable=pages_with_speakable,
        pages_eligible_snippets=pages_eligible_snippets,
    )
    
    # Build the full prompt
    prompt = f"""{SYSTEM_CONTEXT}

## Business Context
- Business: {business_name}
- Industry: {industry}
- Target Audience: {', '.join(target_audience) if target_audience else 'General'}
- Goals: {', '.join(primary_goals) if primary_goals else 'Not specified'}

## Site Summary (from programmatic crawl)
- Total Pages: {total_pages}
- Pages with Schema: {pages_with_schema}
- Pages with H1: {pages_with_h1}
{aeo_geo_context}
## Programmatic Issues Detected (for reference only - do NOT report as inference issues):
- Duplicate Titles: {len(duplicate_titles)} pages
- Duplicate Meta Descriptions: {len(duplicate_meta)} pages  
- Thin Content Pages: {len(thin_content)} pages

Your task: Analyze the page data below for INFERENCE-BASED issues that cannot
be detected programmatically. Focus on:

1. **Content Quality Assessment**:
   - Does page content match the business industry/target audience?
   - Identify thin content that may have adequate word count but LOW semantic value
   - Detect content that contradicts brand voice or messaging
   - Look for keyword stuffing or unnatural content patterns

2. **Semantic SEO Analysis**:
   - Check if page titles/meta descriptions ACCURATELY describe the page content
   - Identify title/tag mismatch (title says X but content is about Y)
   - Assess topical relevance to business goals

3. **Accessibility & UX Signals**:
   - Evaluate image alt text QUALITY (not just presence - are they descriptive?)
   - Check heading hierarchy logical flow (do H2s support H1?)
   - Assess content scannability and readability

4. **Architecture Recommendations**:
   - Analyze internal link structure for silo opportunities
   - Identify orphaned pages (no internal links pointing to them)
   - Suggest URL structure improvements
   - Check for missing pillar/cluster relationships

5. **AEO/GEO Analysis (NEW)**:
   - Answer Readiness: Assess how well content can answer user questions directly
   - Citation Trust: Evaluate likelihood of AI systems citing this content
   - Voice Search Readiness: Check for conversational patterns, question formats
   - Featured Snippet Potential: Identify pages that could win featured snippets
   - Schema Quality for AI: Assess structured data quality for AI citation

## Page Data (sample for analysis):
{str(pages)[:8000]}
{OUTPUT_FORMAT}"""
    
    return prompt
