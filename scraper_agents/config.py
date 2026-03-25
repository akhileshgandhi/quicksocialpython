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
    # Language codes
    r'/(de|fr|es|it|pt|nl|sv|no|da|fi|pl|ru|ja|ko|zh|zh-cn|zh-tw|'
    r'ar|he|th|vi|id|ms|tr|cs|hu|ro|bg|uk|el|hi|bn|'
    # Language-country combos
    r'de-de|fr-fr|es-es|pt-br|pt-pt|ja-jp|ko-kr|zh-hans|zh-hant|'
    r'nl-nl|sv-se|nb-no|da-dk|fi-fi|pl-pl|ru-ru|'
    # Country codes (Apple-style: /jp/, /cn/, /kr/, etc.)
    r'jp|cn|tw|hk|kr|br|mx|cl|co|pe|at|ch|be|lu|'
    r'cz|dk|ie|il|my|ph|sg|za|ae|sa|nz|se|'
    r'gr|hr|sk|si|rs|lt|lv|ee|is)/',
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
