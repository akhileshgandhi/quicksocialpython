"""
ScrapeState — shared mutable state across all agents for a single scrape.

Each agent reads fields written by earlier agents and writes its own output
fields.  No message passing, no event queues — simple and debuggable.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup


@dataclass
class PageInfo:
    """A classified page discovered by the CrawlerAgent."""
    url: str
    title: str = ""
    category: str = "other"   # product | about | service | blog | contact | gallery | careers | other
    priority: int = 3         # 1 (highest) – 5 (lowest)


@dataclass
class ScrapeState:
    """Shared state written / read by every agent during a single scrape."""

    # ── Input (set by Orchestrator before any agent runs) ─────────────────
    scrape_id: str = ""
    website_url: str = ""
    base_url: str = ""
    domain: str = ""
    company_name_hint: Optional[str] = None
    download_logo: bool = True
    deep_scrape: bool = True
    storage_dir: Path = field(default_factory=lambda: Path("generated_images"))

    # ── CrawlerAgent outputs ──────────────────────────────────────────────
    homepage_html: Optional[str] = None
    homepage_soup: Optional[BeautifulSoup] = None
    site_map: Dict[str, List[PageInfo]] = field(default_factory=dict)
    site_type: Optional[str] = None  # ecommerce | saas | restaurant | brand | services | portfolio | platform
    sitemap_urls: List[str] = field(default_factory=list)
    page_cache: Dict[str, str] = field(default_factory=dict)  # URL → HTML
    nav_links: List[Dict[str, Any]] = field(default_factory=list)
    pw_screenshot: Optional[bytes] = None
    pw_computed_colors: list = field(default_factory=list)
    pw_computed_fonts: list = field(default_factory=list)  # [{family, usage, source}] from Playwright JS
    structured_data: List[Dict[str, Any]] = field(default_factory=list)  # JSON-LD
    og_data: Dict[str, str] = field(default_factory=dict)
    favicon_url: Optional[str] = None
    title: str = ""
    meta_description: str = ""
    meta_keywords: str = ""
    headings: List[Dict[str, str]] = field(default_factory=list)
    paragraphs: List[str] = field(default_factory=list)
    about_content: str = ""
    products_content: str = ""
    services_content: str = ""
    full_text: str = ""
    images: List[Dict[str, Any]] = field(default_factory=list)
    logo_candidates: List[Dict[str, Any]] = field(default_factory=list)
    discovered_products: List[Dict[str, Any]] = field(default_factory=list)
    discovered_services: List[Dict[str, Any]] = field(default_factory=list)
    nav_products: List[Dict[str, str]] = field(default_factory=list)
    nav_verticals: List[str] = field(default_factory=list)  # audience/department names from nav (not products)
    listing_urls: List[str] = field(default_factory=list)  # category/listing page URLs for ProductAgent
    visual_analysis: Optional[Dict[str, Any]] = None  # Gemini Vision screenshot analysis

    # ── LogoAgent outputs ─────────────────────────────────────────────────
    logo_url: Optional[str] = None
    logo_local_path: Optional[str] = None
    logo_cloudinary_url: Optional[str] = None
    logo_bytes: Optional[bytes] = None
    logo_ready: asyncio.Event = field(default_factory=asyncio.Event)

    # ── VisualAgent outputs ───────────────────────────────────────────────
    primary_color: Optional[List[str]] = None  # [primary, secondary, accent, background, text]
    secondary_color: Optional[str] = None       # Deprecated — always None
    brand_palette: Optional[Dict[str, str]] = None  # {primary, secondary, accent, background, text}
    color_audit: Optional[Dict[str, Any]] = None  # resolve_brand_palette audit + candidates (persisted)
    headline_text_color: Optional[str] = None
    headline_font: Optional[str] = None
    body_font: Optional[str] = None
    google_fonts_url: Optional[str] = None
    colors_found: List[str] = field(default_factory=list)
    colors_annotated: str = ""
    colors_utility: set = field(default_factory=set)
    fonts_data: List[Dict[str, Any]] = field(default_factory=list)

    # ── ProductAgent outputs ──────────────────────────────────────────────
    products: List[Dict[str, Any]] = field(default_factory=list)
    services: List[Dict[str, Any]] = field(default_factory=list)
    product_image_map: List[Dict[str, Any]] = field(default_factory=list)

    # ── ContentAgent outputs ──────────────────────────────────────────────
    content_assets: List[Dict[str, Any]] = field(default_factory=list)

    # ── ContactAgent outputs ──────────────────────────────────────────────
    social_links: Dict[str, Any] = field(default_factory=dict)
    contact_info: Dict[str, Any] = field(default_factory=dict)

    # ── BrandIntelligenceAgent outputs ────────────────────────────────────
    brand_identity: Dict[str, Any] = field(default_factory=dict)
    seo_social: Dict[str, Any] = field(default_factory=dict)

    # ── Metadata ──────────────────────────────────────────────────────────
    scrape_status: str = "success"
    data_source: str = "hybrid"
    data_gaps: List[str] = field(default_factory=list)
    company_name: str = ""  # resolved name (from Gemini or hint or domain)
