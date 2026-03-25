"""CrawlerAgent prompt — extract products/services from page content."""

CONTENT_ANALYSIS_PROMPT = """\
You are analyzing website content for {company_name} ({website_url}).
Site type: {site_type}

Page content excerpts:
{page_excerpts}

Extract ALL products and services this company offers based on the page content above.

Return JSON:
{{
  "products": [
    {{"name": "...", "description": "...(1-2 sentences max)", "category": "...", "price": "...(if visible, else null)", "source_url": "...(the page URL where this product was found, from the [Page: URL] or [product: URL] header above each excerpt)", "image_url": "...(if an image URL is associated with this product in the text, else null)"}}
  ],
  "services": [
    {{"name": "...", "description": "...(1-2 sentences max)", "category": "...", "pricing": "...(if visible, else null)", "source_url": "...(the page URL where this service was found)", "image_url": "...(if an image URL is associated with this service, else null)"}}
  ]
}}

CRITICAL GROUNDING RULES:
- Extract products/services mentioned, described, or referenced in the text excerpts above
- Use product/service names AS THEY APPEAR on the page — do not combine separate items into one
  - WRONG: "Maggie Tea" (combining "Maggi" and "Tea" into one product)
  - RIGHT: "Maggi" and "Masala Tea" as separate products
  - WRONG: "Premium Deluxe Coffee Experience" (embellishing a simple name)
  - RIGHT: "Cold Coffee" (the actual name on the page)
- For restaurants/cafes: extract ALL menu items, dishes, and beverages — even if only briefly mentioned or listed in passing. Be thorough.
- For source_url: set it to the URL from the excerpt header where the product was found (e.g., if the excerpt starts with "[product: https://example.com/menu]", use "https://example.com/menu")
- For prices: only include prices that appear LITERALLY in the text. If no price is visible, set price/pricing to null
{visual_context}

Site-type guidance:
- Products = physical/digital goods the company sells or showcases
- Services = offerings, subscriptions, platforms the company provides
- For brand sites (FMCG like Dabur, P&G): list individual product brands/lines as products (e.g., "Dabur Red Paste", "Vatika Shampoo", "Real Fruit Juice")
- For food delivery/aggregator platforms: list platform services (e.g., "Food Delivery", "Table Reservation", "Dine-out"), NOT individual restaurants
- For SaaS / platform sites:
  - **Products**: Named product offerings users can buy or use (e.g., "Slack", "Huddles", "Canvas", "Clips", pricing tiers like "Pro", "Business+", "Enterprise Grid")
  - **Services**: Professional services, consulting, implementation, training, support plans
  - **NOT products**: Department or audience names (Engineering, Sales, Marketing, IT, HR, Finance) — these are verticals/use-cases, not things you can buy
  - **NOT products**: Industry segments (Healthcare, Education, Government, Retail) — these are market verticals
  - If the page shows "Solutions for [Department]" or "[Industry] solutions", these are audience segments, NOT products or services
  - Features/capabilities within a product (e.g., "Channels", "Workflows", "Search") can be listed as products only if they are independently named and marketed
- For platform/aggregator sites (Zomato, Uber, Airbnb, DoorDash):
  - **Products**: The platform's own named offerings (e.g., "Zomato Gold", "Uber Eats", "Airbnb Plus", subscription tiers)
  - **Services**: Core platform capabilities (e.g., "Food Delivery", "Table Booking", "Dine-out", "Ride Sharing")
  - **NOT products**: App store listing titles, app download links, third-party app names
  - **NOT products**: Items from external domains (play.google.com, apps.apple.com)
  - The platform itself is the primary product — list its sub-products and service offerings
- For conglomerate/holding company sites (Tata Group, Reliance, Adani, GE, Samsung):
  - **Products**: The subsidiary companies and brands (e.g., "Tata Steel", "TCS", "Tata Motors", "Titan", "Tata Consumer Products")
  - **Services**: Group-level services or initiatives (e.g., "Tata Trusts", "CSR Programs", "Innovation Hub")
  - **NOT products**: News articles, press releases, stories, events, awards, or editorial content featured on the homepage
  - **NOT products**: Books, biographies, individual achievements, or promotional content about the group's history
  - Focus on the GROUP'S BUSINESSES and BRANDS, not ephemeral homepage content
- For e-commerce: list featured products or product categories with examples
- For restaurants: list menu categories and signature dishes as products
- Max 30 products, 15 services
- Include category for grouping (e.g., "Hair Care", "Oral Care", "Electronics")
- Do NOT include navigation items, footer links, page sections, or UI elements as products
- Do NOT include generic terms like "Apps For You" or "About Us" as products
- Return ONLY valid JSON
"""
