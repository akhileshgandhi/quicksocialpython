"""CrawlerAgent prompt — combined visual analysis + site classification (single Gemini call).

Merges the screenshot-based visual analysis with text-based site classification
to save one Gemini API call (~6-8 seconds, ~2000-3000 tokens).
"""

VISUAL_AND_CLASSIFY_PROMPT = """\
You are analyzing a website for {company_name_hint} ({domain}).

Website title: {title}
Meta description: {meta_description}

Navigation links found in HTML:
{nav_links_text}

A screenshot of the homepage is attached. Analyze BOTH the screenshot AND the text above.

Return ONLY a JSON object with these fields:

{{
  "site_type": "<one of: ecommerce, saas, restaurant, brand, services, portfolio, platform, conglomerate>",
  "company_name": "<the brand/company name>",
  "nav_mapping": {{"<visible nav label>": "<product|service|about|blog|contact|gallery|other>"}},
  "image_content": ["<observation about business content embedded in images, e.g. menu cards, price lists — empty list if none>"],
  "product_pages": ["<relative URL paths likely containing products/menu/services, e.g. /menu, /products, /shop>"],
  "links": [
    {{"url": "<full url>", "text": "<link text>", "category": "<product|about|service|blog|contact|gallery|careers|other>", "priority": <1-5>}}
  ]
}}

Site type rules:
- "ecommerce": sells products online (Shopify, WooCommerce, Amazon-style)
- "saas": software/tech product with pricing tiers
- "restaurant": food/beverage service with menu
- "brand": FMCG or consumer brand showcasing products but no direct purchase
- "services": professional/B2B services (consulting, agency)
- "platform": aggregator/marketplace (Zomato, Uber, Paytm)
- "conglomerate": holding company with multiple subsidiary brands (Tata, Reliance)
- "portfolio": personal portfolio or creative showcase

Nav mapping rules (use screenshot context):
- "Menu" on a restaurant = product. "Menu" on a SaaS site = ignore.
- "Our Offerings" / "What We Do" = service
- "Store" / "Shop" / "Products" / "Collection" = product
- "Gallery" / "Portfolio" / "Our Work" = gallery
- "Blog" / "News" / "Resources" = blog
- "Contact" / "Get in Touch" = contact

Category rules for links:
- "product": pages listing products, shop, store, catalog, menu, pricing
- "about": about us, our story, team
- "service": services, solutions, what we do
- "blog": blog, news, articles, resources
- "contact": contact us, support, help
- "gallery": gallery, portfolio, case studies
- "careers": careers, jobs, hiring
- "other": login, cart, legal, privacy

Return ONLY valid JSON, no markdown fences.
"""

# Fallback text-only prompt (when no screenshot available)
CLASSIFY_ONLY_PROMPT = """\
You are a website structure analyst. Given a website's title, meta description, and navigation links, classify the site and categorize every link.

Website title: {title}
Meta description: {meta_description}
Domain: {domain}

Navigation links:
{nav_links_text}

Return ONLY a JSON object with:
{{
  "site_type": "<one of: ecommerce, saas, restaurant, brand, services, portfolio, platform, conglomerate>",
  "company_name": "<the brand/company name>",
  "links": [
    {{"url": "<full url>", "text": "<link text>", "category": "<one of: product, about, service, blog, contact, gallery, careers, other>", "priority": <1-5 where 1=highest>}}
  ]
}}

Site type rules:
- "ecommerce": sells products online (Shopify, WooCommerce, Amazon-style)
- "saas": software/tech product with pricing tiers
- "restaurant": food/beverage service with menu
- "brand": FMCG or consumer brand with product showcases but no direct purchase
- "services": professional/B2B services (consulting, agency, freelance)
- "platform": aggregator or marketplace (food delivery, ride-sharing, fintech)
- "conglomerate": large holding company with multiple subsidiary brands
- "portfolio": personal portfolio or creative showcase

Category rules:
- "product": pages listing or describing products, shop, store, catalog, menu, pricing
- "about": about us, our story, team, company info
- "service": services offered, solutions, what we do
- "blog": blog, news, articles, insights, resources
- "contact": contact us, get in touch, support, help
- "gallery": gallery, portfolio, case studies, our work
- "careers": careers, jobs, hiring, work with us
- "other": anything else (login, cart, legal, privacy)

Priority: 1 = essential for brand understanding, 5 = skip.
{visual_context}
Return ONLY valid JSON, no markdown fences.
"""
