"""CrawlerAgent prompt — classify site type and categorize nav links."""

SITE_CLASSIFICATION_PROMPT = """\
You are a website structure analyst. Given a website's title, meta description, and navigation links, classify the site and categorize every link.

Website title: {title}
Meta description: {meta_description}
Domain: {domain}

Navigation links:
{nav_links_text}

Return ONLY a JSON object with:
{{
  "site_type": "<one of: ecommerce, saas, restaurant, brand, services, portfolio, platform>",
  "company_name": "<the brand/company name>",
  "links": [
    {{"url": "<full url>", "text": "<link text>", "category": "<one of: product, about, service, blog, contact, gallery, careers, other>", "priority": <1-5 where 1=highest>}}
  ]
}}

Classification rules:
- "ecommerce": sells products online (Shopify, WooCommerce, Amazon-style)
- "saas": software/tech product with pricing tiers
- "restaurant": food/beverage service with menu
- "brand": FMCG or consumer brand (like Dabur, Nike) with product showcases but no direct purchase
- "services": professional/B2B services (consulting, agency, freelance)
- "platform": aggregator or marketplace connecting users with providers (food delivery like Zomato/DoorDash, ride-sharing like Uber, gig platforms like TaskRabbit, booking platforms like Airbnb, fintech like Paytm/PhonePe). The company itself is the product — it does NOT sell physical goods
- "conglomerate": large holding company or group with multiple subsidiary companies/brands across different industries (e.g., Tata Group, Reliance, Samsung, GE, Unilever, Adani). The website showcases the group's portfolio of businesses, NOT individual products
- "portfolio": personal portfolio or creative showcase

Category rules:
- "product": pages listing or describing products, shop, store, catalog, menu, pricing, our businesses, our companies, our brands, subsidiaries
- "about": about us, our story, team, company info, who we are
- "service": services offered, solutions, what we do, offerings
- "blog": blog, news, articles, insights, resources, press, updates
- "contact": contact us, get in touch, support, help, locations
- "gallery": gallery, portfolio, case studies, our work, projects
- "careers": careers, jobs, hiring, work with us, join us
- "other": anything else (login, cart, legal, privacy, terms)

Priority: 1 = essential for brand understanding, 5 = skip.
{visual_context}
Return ONLY valid JSON, no markdown fences.
"""
