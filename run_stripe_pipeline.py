#!/usr/bin/env python3
"""
Stripe SEO Agent Pipeline - Runs Agent 01 (Intake) then Agent 02 (Crawl)

Configurable crawl settings via config:
    max_pages: 50-200 for small/medium sites
    crawl_depth: 2-3 for most sites
"""

import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')

from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
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
    
    agent_01 = IntakeAgent(None, 'meta-llama/llama-4-scout-17b-16e-instruct', storage_dir)
    await agent_01.execute(state)
    
    print('Output: seo_project_context')
    print('-'*40)
    print(json.dumps(state.seo_project_context, indent=2))
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
    
    agent_02 = CrawlAgent(None, 'meta-llama/llama-4-scout-17b-16e-instruct', storage_dir)
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
    print('PIPELINE COMPLETE')
    print('='*60)
    print(f'Project: {project_id}')
    print(f'Website: {state.seo_project_context.get("website_url")}')
    print(f'Pages crawled: {inv.get("total_pages")}')
    print(f'Depth reached: {inv.get("crawl_depth_reached")}')
    print('')


if __name__ == '__main__':
    main()
