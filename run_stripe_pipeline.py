#!/usr/bin/env python3
"""
Stripe SEO Agent Pipeline - Runs Agent 01 → 02 → 03 → 04

This pipeline tests the enhanced SEO workflow:
- Agent 01: Intake (business context)
- Agent 02: Crawl (site inventory with SEO enhancements)
- Agent 03: Technical Audit (inference-based analysis)
- Agent 04: Keyword Research (AEO/GEO enhancements)

Configurable crawl settings via config:
    max_pages: 50-200 for small/medium sites
    crawl_depth: 2-3 for most sites
"""

import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)
sys.stdout.reconfigure(encoding='utf-8')

from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.technical import TechnicalAuditAgent
from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.state import SEOState, save_seo_state


# Configuration - adjust these values
CRAWL_CONFIG = {
    'crawl_depth': 3,   # Depth 2-3 is typically sufficient
    'max_pages': 50,   # 50 for small sites, 100-200 for medium
}


def format_list(items, max_display=3):
    if not items:
        return '[]'
    displayed = items[:max_display]
    result = ', '.join(str(i) for i in displayed)
    if len(items) > max_display:
        result += f' (+{len(items) - max_display} more)'
    return f'[{result}]'


def main():
    STORAGE_DIR = Path('./generated_images')
    asyncio.run(run_pipeline(STORAGE_DIR))


async def run_pipeline(storage_dir):
    project_id = 'stripe_project'
    project_dir = storage_dir / 'seo_projects' / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    
    print('='*60)
    print('AGENT 01: IntakeAgent')
    print('='*60)
    
    stripe_data = {
        'business_name': 'Stripe',
        'website_url': 'https://stripe.com',
        'industry': 'Financial Technology / Payments',
        'target_audience': ['Businesses', 'Developers', 'SaaS companies'],
        'primary_goals': ['Process payments securely', 'Increase transaction volume', 'Reduce churn'],
        'competitors': ['PayPal', 'Square', 'Adyen', 'Braintree'],
        'brand_voice': 'Professional, secure, innovative, developer-friendly',
        'key_products_services': ['Payment processing', 'Stripe Atlas', 'Stripe Capital', 'Radar fraud detection'],
    }
    
    state = SEOState(
        project_id=project_id,
        brand_id='stripe',
        website_url='https://stripe.com',
        config={
            **CRAWL_CONFIG,
            'target_geography': 'Global',
            'intake_form_data': stripe_data,
        }
    )
    
    print(f'Config: crawl_depth={CRAWL_CONFIG["crawl_depth"]}, max_pages={CRAWL_CONFIG["max_pages"]}')
    print('')
    
    import google.genai as genai
    import os
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        api_key = 'AIzaSyCt10dVCIUpKelnHqrlStbqPpM_Ymugko0'
    gemini_client = genai.Client(api_key=api_key)
    
    agent_01 = IntakeAgent(gemini_client, 'gemini-2.5-flash-lite', storage_dir)
    await agent_01.execute(state)
    
    # Format Agent 01 output nicely
    ctx = state.seo_project_context
    if hasattr(ctx, 'model_dump'):
        ctx = ctx.model_dump()
    
    print('='*60)
    print('PROJECT CONTEXT (Agent 01)')
    print('='*60)
    print(f"\nBusiness: {ctx.get('business_name', 'N/A')}")
    print(f"Website: {ctx.get('website_url', 'N/A')}")
    print(f"Industry: {ctx.get('industry', 'N/A')}")
    print(f"Geographic Focus: {ctx.get('geographic_focus', 'N/A')}")
    
    audience = ctx.get('target_audience', [])
    print(f"\nTarget Audience: {format_list(audience, 5)}")
    
    goals = ctx.get('primary_goals', [])
    print(f"Primary Goals: {format_list(goals, 3)}")
    
    products = ctx.get('key_products_services', [])
    print(f"Products/Services: {format_list(products, 5)}")
    
    competitors = ctx.get('competitors', [])
    print(f"Competitors: {format_list(competitors, 5)}")
    
    voice = ctx.get('brand_voice', 'N/A')
    print(f"\nBrand Voice: {voice}")
    print('')
    save_seo_state(state, storage_dir)
    print(f'Saved to: {project_dir}/project.json')
    print('')
    
    print('='*60)
    print('AGENT 02: CrawlAgent (Enhanced SEO)')
    print('='*60)
    print(f"Input: website_url = '{state.seo_project_context.get('website_url')}'")
    print(f"Config: crawl_depth = {state.config.get('crawl_depth')}, max_pages = {state.config.get('max_pages')}")
    print('')
    
    agent_02 = CrawlAgent(gemini_client, 'gemini-2.5-flash-lite', storage_dir)
    await agent_02.execute(state)
    
    inventory = state.site_inventory
    if hasattr(inventory, 'model_dump'):
        inv = inventory.model_dump()
    else:
        inv = inventory
    
    print('='*60)
    print('ENHANCED SEO INVENTORY')
    print('='*60)
    
    print('\nCrawl Summary:')
    print(f'  Total pages crawled: {inv.get("total_pages", 0)}')
    print(f'  Depth reached: {inv.get("crawl_depth_reached", 0)}')
    print(f'  Avg response time: {inv.get("avg_response_time_ms", 0)}ms')
    
    print('\nSEO Metrics:')
    print(f'  Pages with H1: {inv.get("pages_with_h1", 0)}')
    print(f'  Pages with meta description: {inv.get("pages_with_meta_description", 0)}')
    print(f'  Pages with Schema.org: {inv.get("pages_with_schema", 0)}')
    print(f'  Pages with Open Graph: {inv.get("pages_with_og_tags", 0)}')
    
    sitemap = inv.get('sitemap', {})
    if hasattr(sitemap, 'model_dump'):
        sitemap = sitemap.model_dump()
    robots = inv.get('robots_txt', {})
    if hasattr(robots, 'model_dump'):
        robots = robots.model_dump()
    
    print('\nTechnical Files:')
    sm_url = sitemap.get('url', '') if sitemap.get('found') else 'Not found'
    print(f'  Sitemap.xml: {sm_url}')
    rb_url = robots.get('url', '') if robots.get('found') else 'Not found'
    print(f'  robots.txt: {rb_url}')
    
    print('\nSecurity:')
    print(f'  HTTPS only: {"Yes" if inv.get("is_https_only") else "No"}')
    print(f'  SSL issues: {"Yes" if inv.get("has_ssl_issues") else "No"}')
    
    dup_titles = inv.get('duplicate_titles', [])
    dup_meta = inv.get('duplicate_meta_descriptions', [])
    thin = inv.get('thin_content_pages', [])
    
    print('\nContent Issues:')
    print(f'  Duplicate titles: {len(dup_titles)}')
    print(f'  Duplicate meta descriptions: {len(dup_meta)}')
    print(f'  Thin content pages: {len(thin)}')
    
    total_pages_crawled = inv.get('total_pages', 0)
    display_count = min(10, total_pages_crawled)
    
    print(f'\nPages (first {display_count} of {total_pages_crawled}):')
    pages = inv.get('pages', [])
    for i, page in enumerate(pages[:display_count], 1):
        if hasattr(page, 'model_dump'):
            page = page.model_dump()
        
        print(f'  {i}. {page.get("url")}')
        print(f'     Status: {page.get("status_code")} | Words: {page.get("word_count")} | Response: {page.get("response_time_ms")}ms')
        
        h1 = page.get('h1')
        if h1:
            h1_short = h1[:40] + '...' if len(h1) > 40 else h1
            print(f'     H1: {h1_short}')
        
        h2_tags = page.get('h2_tags', [])
        if h2_tags:
            print(f'     H2 tags: {format_list(h2_tags)}')
        
        canonical = page.get('canonical_url')
        if canonical:
            print(f'     Canonical: {canonical}')
        
        schema = page.get('schema_types', [])
        if schema:
            print(f'     Schema: {format_list(schema)}')
        
        images = page.get('images', [])
        if images:
            print(f'     Images: {len(images)} (opt: {not page.get("has_unoptimized_images", True)})')
        
        og = page.get('og_tags')
        if og:
            og_dict = og.model_dump() if hasattr(og, 'model_dump') else og
            og_title = og_dict.get('og_title', '')
            if og_title:
                og_short = og_title[:30] + '...' if len(og_title) > 30 else og_title
                print(f'     OG Title: {og_short}')
        
        internal = page.get('internal_links', [])
        external = page.get('external_links', [])
        print(f'     Links: {len(internal)} internal, {len(external)} external')
    
    print('')
    save_seo_state(state, storage_dir)
    print(f'Saved to: {project_dir}/project.json')
    print('')
    
    print('='*60)
    print('AGENT 03: TechnicalAuditAgent (Inference-Based)')
    print('='*60)
    print('Input: site_inventory + seo_project_context')
    print('Focus: Content quality, semantic analysis, accessibility, architecture')
    print('')
    
    agent_03 = TechnicalAuditAgent(gemini_client, 'gemini-2.5-flash-lite', storage_dir)
    await agent_03.execute(state)
    
    audit_report = state.technical_audit_report
    if hasattr(audit_report, 'model_dump'):
        report = audit_report.model_dump()
    else:
        report = audit_report
    
    print('='*60)
    print('TECHNICAL AUDIT REPORT')
    print('='*60)
    
    print(f'\nHealth Score: {report.get("overall_health_score")}/100')
    print(f'Total Inference Issues: {report.get("total_inference_issues")}')
    
    crit = report.get('inference_critical', [])
    warns = report.get('inference_warnings', [])
    infos = report.get('inference_info', [])
    
    print(f'  Critical: {len(crit)}')
    print(f'  Warnings: {len(warns)}')
    print(f'  Info: {len(infos)}')
    
    prog = report.get('programmatic_summary', {})
    print('\nProgrammatic Issues (from Agent 02):')
    print(f'  Duplicate titles: {prog.get("duplicate_titles_count", 0)}')
    print(f'  Duplicate meta descriptions: {prog.get("duplicate_meta_count", 0)}')
    print(f'  Thin content pages: {prog.get("thin_content_count", 0)}')
    print(f'  Pages missing H1: {prog.get("pages_missing_h1_count", 0)}')
    print(f'  Broken links: {prog.get("broken_links_count", 0)}')
    
    if crit:
        print('\nCritical Issues:')
        for issue in crit:
            desc = issue.get('description', '')[:60]
            print(f'  - [{issue.get("issue_type")}] {desc}...')
    
    if warns:
        print('\nWarnings:')
        for issue in warns[:3]:
            desc = issue.get('description', '')[:60]
            print(f'  - [{issue.get("issue_type")}] {desc}...')
    
    print('')
    save_seo_state(state, storage_dir)
    print(f'Saved to: {project_dir}/project.json')
    print('')
    
    print('='*60)
    print('AGENT 04: KeywordResearchAgent (AEO/GEO Enhancements)')
    print('='*60)
    print('Input: seo_project_context + site_inventory')
    print('Focus: AEO/GEO keyword research with answer surfaces')
    print('')

    # Note: In the new architecture, Agent 08 (Competitor) runs AFTER Agent 04
    # So competitor_matrix is NOT available for this agent
    agent_04 = KeywordResearchAgent(gemini_client, 'gemini-2.5-flash-lite', storage_dir)
    await agent_04.execute(state)
    
    keyword_universe = state.keyword_universe
    if hasattr(keyword_universe, 'model_dump'):
        universe = keyword_universe.model_dump()
    else:
        universe = keyword_universe
    
    print('='*60)
    print('KEYWORD UNIVERSE (AEO/GEO ENHANCED)')
    print('='*60)
    
    print(f'\nTotal Keywords: {universe.get("total_keywords", 0)}')
    
    # AEO/GEO Summary fields
    print('\nAEO/GEO Opportunities:')
    print(f'  Featured Snippet: {universe.get("featured_snippet_opportunities", 0)}')
    print(f'  Voice Search: {universe.get("voice_search_opportunities", 0)}')
    print(f'  AI Overview: {universe.get("ai_overview_opportunities", 0)}')
    print(f'  High Citation Value: {universe.get("high_citation_value_keywords", 0)}')
    
    seed_terms = universe.get('seed_terms_used', [])
    print(f'\nSeed Terms Used: {format_list(seed_terms, 5)}')
    
    keywords = universe.get('keywords', [])
    display_kw_count = min(10, len(keywords))
    
    print(f'\nSample Keywords (first {display_kw_count}):')
    for i, kw in enumerate(keywords[:display_kw_count], 1):
        if hasattr(kw, 'model_dump'):
            kw = kw.model_dump()
        
        keyword = kw.get('keyword', '')
        intent = kw.get('intent', '')
        volume = kw.get('volume_tier', '')
        competition = kw.get('competition_tier', '')
        query_format = kw.get('query_format', '')
        citation = kw.get('citation_value_score', 0)
        surfaces = kw.get('answer_surfaces', [])
        
        # Format answer surfaces for display
        surface_str = ', '.join(str(s).replace('_', ' ') for s in surfaces[:3]) if surfaces else 'none'
        
        print(f'  {i}. {keyword}')
        print(f'     Intent: {intent} | Volume: {volume} | Competition: {competition}')
        print(f'     Format: {query_format} | Citation Score: {citation}/10')
        print(f'     Answer Surfaces: {surface_str}')
    
    print('')
    save_seo_state(state, storage_dir)
    print(f'Saved to: {project_dir}/project.json')
    print('')
    
    print('='*60)
    print('PIPELINE COMPLETE (Agents 01-05)')
    print('='*60)
    print(f'Project: {project_id}')
    print(f'Website: {state.seo_project_context.get("website_url")}')
    print(f'Pages crawled: {inv.get("total_pages")}')
    print(f'Depth reached: {inv.get("crawl_depth_reached")}')
    print(f'Health Score: {report.get("overall_health_score")}/100')
    print(f'Total Keywords: {universe.get("total_keywords", 0)}')
    print(f'AEO Opportunities: {universe.get("featured_snippet_opportunities", 0)} featured, {universe.get("ai_overview_opportunities", 0)} AI Overview')
    print('')


if __name__ == '__main__':
    main()
