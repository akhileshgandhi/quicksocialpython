"""CrawlerAgent prompt — visual analysis of website screenshot via Gemini Vision."""

VISUAL_ANALYSIS_PROMPT = """\
You are analyzing a screenshot of the homepage for {company_name} ({domain}).

Navigation links found in HTML:
{nav_links_text}

Analyze this screenshot and provide:

1. **nav_mapping**: For each VISIBLE navigation label, map it to a content type.
   Industry context matters:
   - "Menu" on a restaurant = product (food items). "Menu" on a SaaS site = ignore (it's just navigation).
   - "Our Offerings" / "What We Do" = service
   - "Store" / "Shop" / "Products" / "Collection" = product
   - "Gallery" / "Portfolio" / "Our Work" = gallery
   - "About" / "Our Story" / "Who We Are" = about
   - "Blog" / "News" / "Insights" / "Resources" = blog
   - "Contact" / "Get in Touch" / "Book a Table" / "Locate Us" = contact
   - "Franchise" / "Partner" / "Careers" = other

2. **image_content**: Identify any important business content that appears to be embedded
   in IMAGES rather than HTML text. Examples:
   - Restaurant menu cards where food items + prices are baked into JPG/PNG images
   - Product catalogs displayed as image-only cards (no HTML text underneath)
   - Price lists rendered as images
   - Infographics with key business data
   If none detected, return an empty list.

3. **layout_notes**: Brief description of the visual layout and key content sections visible.

4. **product_pages**: Based on the navigation and visual cues, which relative URL paths
   likely contain the business's products, menu items, or service offerings?
   Return paths like "/menu", "/products", "/our-services", "/shop", etc.

5. **site_type_hint**: Based on visual appearance, what type of site is this?
   One of: ecommerce, saas, restaurant, brand, services, portfolio, platform, conglomerate

Return ONLY a JSON object (no markdown fences):
{{"nav_mapping": {{"<visible nav label>": "<product|service|about|blog|contact|gallery|other>"}}, "image_content": ["<observation about content in images>"], "layout_notes": "<brief layout description>", "product_pages": ["<relative URL path>"], "site_type_hint": "<site type>"}}
"""
