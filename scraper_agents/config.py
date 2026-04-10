"""
Centralized configuration for the agentic scraper.

All timeouts, thresholds, and score weights live here — nothing hardcoded
inside individual agents or extractors.
"""

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------
TIMEOUTS = {
    # HTTP requests (seconds)
    "http_request": 10,
    "css_fetch": 5,
    "sitemap_fetch": 10,
    "product_detail_fetch": 10,
    "asset_enrich_fetch": 10,
    "logo_download": 15,
    "logo_probe": 4,

    # Playwright (milliseconds)
    "page_load_ms": 15_000,
    "page_render_wait_ms": 3_000,

    # asyncio.to_thread wrapper (seconds) — must exceed PW timeouts
    "playwright_thread": 40,
    "svg_conversion_thread": 30,

    # Gemini API (seconds)
    "visual_analysis": 15,  # Gemini Vision screenshot analysis
    "gemini_call": 60,
}

# ---------------------------------------------------------------------------
# Concurrency limits
# ---------------------------------------------------------------------------
CONCURRENCY = {
    "page_cache_workers": 6,       # CrawlerAgent: concurrent page fetches
    "product_detail_workers": 15,  # ProductAgent: concurrent product page scrapes
    "asset_enrich_workers": 4,     # ContentAgent: concurrent asset enrichments
    "max_cached_pages": 10,        # CrawlerAgent: max pages to pre-fetch
    "max_product_pages": 300,      # ProductAgent: max product detail pages
    "max_listing_pages": 20,       # ProductAgent: max listing/category pages
    "max_asset_enrichments": 12,   # ContentAgent: max assets to enrich
}

# ---------------------------------------------------------------------------
# Agent time budgets (seconds) — agent stops gracefully when budget expires
# ---------------------------------------------------------------------------
AGENT_TIME_BUDGETS = {
    "crawler": 75,
    "logo": 45,
    "visual": 20,
    "products": 60,
    "content": 30,
    "contact": 15,
    "brand_intelligence": 30,
    "web_search": 20,
}

# ---------------------------------------------------------------------------
# Logo scoring weights
# ---------------------------------------------------------------------------
LOGO_SCORE = {
    "keyword_logo": 5,
    "keyword_brand": 3,
    "home_link": 9,
    "priority_selector": 10,
    "preferred_corner_bonus": 65,
    "loyalty_margin": 15,
    "external_link_penalty": -25,
    "foreign_company_penalty": -15,
    "icon_penalty": -5,
    "white_variant_penalty": -8,
    "company_slug_affinity": 8,
    "high_confidence_threshold": 10,
    # When logo_wordmark_preference is True: wide lockups vs small square icons
    "wordmark_wide_bonus": 8,
    "home_square_icon_penalty": -6,
}

# ---------------------------------------------------------------------------
# Color extraction
# ---------------------------------------------------------------------------
COLOR_CONFIG = {
    # Source weights (used in merged ranking)
    "weight_logo_kmeans": 10,
    "weight_meta_theme": 10,
    "weight_css_brand_var": 5,
    "weight_pw_computed": 8,
    "weight_inline_key_element": 3,
    "weight_external_css": 2,
    "weight_style_tag": 1,
    "weight_screenshot_kmeans": 3,
    "weight_gemini_vision": 5,

    # K-means parameters
    "kmeans_iterations": 20,
    "kmeans_min_distance": 60,
    "kmeans_max_colors": 5,

    # Filtering
    "near_white_threshold": 220,   # R,G,B all > this → near-white
    "gray_spread_threshold": 25,   # max-min < this → achromatic
    "gray_brightness_min": 70,     # R > this and achromatic → mid-gray

    # resolve_brand_palette: SaaS-like sites use website primary when logo is weak
    "palette_logo_saturation_floor": 38.0,
    "palette_hue_crosscheck_deg": 45.0,
}

# Bumped when color candidate ordering, resolve_brand_palette rules, or audit shape changes.
COLOR_PIPELINE_VERSION = "2026.04.07"

# ---------------------------------------------------------------------------
# Logo agent (feature flags + Playwright tuning)
# ---------------------------------------------------------------------------
LOGO_CONFIG = {
    # When True: run Gemini logo search if no logo yet after earlier strategies,
    # even when HTML candidates exist (fixes wrong-first-pick / all-failed-downloads).
    "expand_gemini_fallback": True,
    # Hosts that may serve first-party logos (JSON-LD / OG may point here)
    "trusted_logo_cdn_hosts": frozenset({
        "cdn.shopify.com",
        "cdn.shopifycdn.net",
        "images.ctfassets.net",
        "res.cloudinary.com",
        "media.graphassets.com",
        "static.wixstatic.com",
        "assets.squarespace.com",
        "framerusercontent.com",
        "images.prismic.io",
        "cdn.sanity.io",
        "lh3.googleusercontent.com",
        # Zomato / Blinkit first-party CDN (og:image / static assets)
        "b.zmtcdn.com",
        # JSON-LD Organization.logo on Vercel-hosted marketing sites
        "public.blob.vercel-storage.com",
        "blob.vercel-storage.com",
    }),
    # Playwright: default preserves legacy behavior; enable for JS-heavy headers
    "playwright_aggressive_render": False,
    "playwright_wait_until": "domcontentloaded",  # "load" | "networkidle" when aggressive
    "playwright_extra_wait_ms": 0,
    "playwright_wait_for_logo_selectors": True,
    "playwright_extract_computed_background": True,
    # Video poster + <picture> sources in header/nav only (try/except in agent)
    "playwright_header_media_extras": True,
    # Hover brand area once to capture hover-swapped marks (off by default)
    "playwright_hover_logo_probe": False,
    "playwright_hover_settle_ms": 500,
    # P1 logo pipeline: prefer inline SVG from canonical home link (Notion/GitHub-class)
    # before ranked raster <img> candidates; falls back to existing waterfall on failure.
    "logo_svg_home_capture": True,
    # Boost wide wordmarks; slight penalty for small squares on home link (icon vs lockup).
    "logo_wordmark_preference": True,
    # Reserved: pick best of top candidates via Gemini vision (off by default).
    "logo_gemini_candidate_verify": False,
    # Extra settle time for A3 home-SVG (SVG hydration on SPAs).
    "logo_svg_home_extra_wait_ms": 1500,
    # Reject raster logos that look like favicons / nav sprites (see validate_logo_image).
    "logo_reject_favicon_square_max": 128,
    "logo_marketing_min_height_px": 28,
}

# ---------------------------------------------------------------------------
# Third-party widget CSS class prefixes (colors from these are NOT brand)
# ---------------------------------------------------------------------------
import re

THIRD_PARTY_WIDGET_RE = re.compile(
    r'\.(jdgm-|yotpo-|trustpilot-|stamped-|loox-|klaviyo-|'
    r'quinn-|smile-|rebuy-|omnisend-|privy-|gorgias-|'
    r'tidio-|intercom-|drift-|tawk-|crisp-|'
    r'spr-|okeReviews|rivyo-|vitals-|judge-)',
    re.IGNORECASE,
)

# CDN domains that serve first-party theme CSS (not truly third-party)
THEME_CDN_DOMAINS = [
    'cdn.shopify.com',
    'assets.squarespace.com',
    'static.wixstatic.com',
    'assets.bigcommerce.com',
]

# ---------------------------------------------------------------------------
# Product image filtering
# ---------------------------------------------------------------------------
PRODUCT_IMAGE_REJECT_PATTERNS = re.compile(
    r'banner|slider|carousel|hero|promo|placeholder|sprite',
    re.IGNORECASE,
)
PRODUCT_IMAGE_MAX_ASPECT_RATIO = 3.0  # width/height > this → banner-like

# ---------------------------------------------------------------------------
# Sitemap / product URL patterns
# ---------------------------------------------------------------------------
PRODUCT_URL_PATTERNS = ['/products/', '/shop/', '/catalog/', '/store/', '/item/']

# Non-English locale path segments — URLs matching this are skipped in sitemap
# parsing and product catalog crawling.  English variants (/en/, /en-us/) are
# deliberately omitted so they pass through.
LOCALE_PATH_RE = re.compile(
    r'/(de|fr|es|it|pt|nl|sv|no|da|fi|pl|ru|ja|ko|zh|zh-cn|zh-tw|'
    r'ar|he|th|vi|id|ms|tr|cs|hu|ro|bg|uk|el|hi|bn|'
    r'de-de|fr-fr|es-es|pt-br|pt-pt|ja-jp|ko-kr|zh-hans|zh-hant|'
    r'nl-nl|sv-se|nb-no|da-dk|fi-fi|pl-pl|ru-ru)/',
    re.IGNORECASE,
)
TAXONOMY_SEGMENTS = {
    'brands', 'brand', 'collections', 'collection', 'categories', 'category',
    'flavour', 'flavours', 'flavor', 'flavors', 'type', 'types', 'tag', 'tags',
}

# ---------------------------------------------------------------------------
# User-Agent header
# ---------------------------------------------------------------------------
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {"User-Agent": DEFAULT_USER_AGENT}
