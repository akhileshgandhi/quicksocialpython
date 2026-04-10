"""
CrawlerAgent — maps site structure, classifies pages, caches HTML.

Runs first (blocking).  All other agents depend on its output.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper_agents.agents.base import BaseAgent
from scraper_agents.config import (
    CONCURRENCY,
    DEFAULT_HEADERS,
    DEFAULT_USER_AGENT,
    LOCALE_PATH_RE,
    PRODUCT_URL_PATTERNS,
    TIMEOUTS,
)
from scraper_agents.extractors.html_helpers import (
    domain_from_url,
    extract_all_images,
    extract_favicon,
    extract_headings,
    extract_jsonld,
    extract_jsonld_logo,
    extract_jsonld_products,
    extract_meta,
    extract_nav_links,
    extract_nav_products,
    extract_og_data,
    extract_paragraphs,
    extract_title,
    make_absolute_url,
    nav_products_are_taxonomy,
    nav_products_are_verticals,
)
from scraper_agents.prompts.content_analysis import CONTENT_ANALYSIS_PROMPT
from scraper_agents.prompts.site_classification import SITE_CLASSIFICATION_PROMPT
from scraper_agents.state import PageInfo, ScrapeState

logger = logging.getLogger(__name__)

# Playwright JS snippet for computed-style color extraction
_PW_COLOR_JS = """(() => {
    const results = [];
    const seen = new Set();
    function addColor(raw, source, isBrand) {
        if (!raw || raw === 'rgba(0, 0, 0, 0)' || raw === 'transparent') return;
        const m = raw.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
        if (!m) return;
        const [r, g, b] = [+m[1], +m[2], +m[3]];
        const h = '#' + [r,g,b].map(c => c.toString(16).padStart(2,'0')).join('').toUpperCase();
        if (seen.has(h)) return;
        seen.add(h);
        results.push({hex: h, source: source, isBrand: isBrand});
    }
    const root = getComputedStyle(document.documentElement);
    // Fixed prefixes x color keywords
    for (const name of ['primary','secondary','accent','brand','theme','main']) {
        for (const pfx of ['--','--color-','--c-','--clr-','--p-color-','--sk-color-','--ds-']) {
            const v = root.getPropertyValue(pfx+name).trim();
            if (v) addColor(v, 'css-var:'+pfx+name, true);
        }
    }
    // Scan ALL custom properties on :root for color-related names
    try {
        for (const sheet of document.styleSheets) {
            try {
                for (const rule of sheet.cssRules || []) {
                    if (rule.selectorText && /^:root|html|\\[data-theme/i.test(rule.selectorText)) {
                        for (let i = 0; i < rule.style.length; i++) {
                            const prop = rule.style[i];
                            if (!prop.startsWith('--')) continue;
                            const lp = prop.toLowerCase();
                            if (/(brand|primary|accent|theme|main)/.test(lp) && /colou?r/.test(lp)) {
                                const v = rule.style.getPropertyValue(prop).trim();
                                if (v) addColor(v, 'css-var:'+prop, true);
                            }
                        }
                    }
                }
            } catch(e) {} // CORS-blocked sheets
        }
    } catch(e) {}
    for (const sel of ['header','[class*="header"]','nav','[class*="nav"]','[role="banner"]']) {
        try { const el = document.querySelector(sel);
            if (el) addColor(getComputedStyle(el).backgroundColor,'header-bg',true);
        } catch(e) {}
    }
    for (const sel of ['button','.btn','.cta','[class*="btn"]','a[class*="button"]']) {
        try { const els = document.querySelectorAll(sel);
            for (let i=0; i<Math.min(els.length,5); i++) addColor(getComputedStyle(els[i]).backgroundColor,'button-bg',true);
        } catch(e) {}
    }
    try { const link = document.querySelector('a[href]');
        if (link) addColor(getComputedStyle(link).color,'link-color',true);
    } catch(e) {}
    try { const ft = document.querySelector('footer,[class*="footer"]');
        if (ft) addColor(getComputedStyle(ft).backgroundColor,'footer-bg',false);
    } catch(e) {}
    return results;
})()"""

# Playwright JS snippet for computed font extraction from rendered DOM
_PW_FONT_JS = """(() => {
    const results = [];
    const seen = new Set();
    function addFont(family, usage, source) {
        if (!family) return;
        // Take first font from comma-separated list
        family = family.split(',')[0].trim().replace(/['"]/g, '');
        if (!family || family === 'inherit' || family === 'initial') return;
        const key = family.toLowerCase();
        if (seen.has(key)) return;
        seen.add(key);
        results.push({family: family, usage: usage, source: source});
    }
    // Check headings
    for (const sel of ['h1','h2','h3']) {
        try {
            const el = document.querySelector(sel);
            if (el) addFont(getComputedStyle(el).fontFamily, 'heading', 'computed:'+sel);
        } catch(e) {}
    }
    // Check body/paragraph
    for (const sel of ['body','p','main']) {
        try {
            const el = document.querySelector(sel);
            if (el) addFont(getComputedStyle(el).fontFamily, 'body', 'computed:'+sel);
        } catch(e) {}
    }
    // Check nav
    try {
        const nav = document.querySelector('nav a, header a');
        if (nav) addFont(getComputedStyle(nav).fontFamily, 'body', 'computed:nav');
    } catch(e) {}
    return results;
})()"""


class CrawlerAgent(BaseAgent):
    agent_name = "crawler"

    async def run(self, state: ScrapeState) -> None:
        url = state.website_url
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
            state.website_url = url

        parsed = urlparse(url)
        state.domain = parsed.netloc.replace("www.", "")
        state.base_url = f"{parsed.scheme}://{parsed.netloc}"

        # Step 1: Fetch homepage
        html = await self._fetch_homepage(state)
        if not html:
            state.scrape_status = "failed"
            return

        state.homepage_html = html
        state.homepage_soup = BeautifulSoup(html, "html.parser")
        soup = state.homepage_soup

        # Step 2: Extract all metadata from homepage
        state.title = extract_title(soup)
        state.meta_description = extract_meta(soup, "description")
        state.meta_keywords = extract_meta(soup, "keywords")
        state.og_data = extract_og_data(soup)
        state.structured_data = extract_jsonld(soup)
        state.nav_links = extract_nav_links(soup, state.base_url)
        state.headings = extract_headings(soup)
        state.paragraphs = extract_paragraphs(soup)
        state.favicon_url = extract_favicon(soup, state.base_url)
        state.images = extract_all_images(soup, state.base_url)
        state.nav_products = extract_nav_products(soup, state.base_url)

        # Full text for brand analysis
        body = soup.find("body")
        if body:
            state.full_text = body.get_text(separator=" ", strip=True)[:10_000]

        self.log(f"title='{state.title}', nav_links={len(state.nav_links)}, images={len(state.images)}, nav_products={len(state.nav_products)}")

        # Steps 2.5+2.7 (Playwright + Visual) run in PARALLEL with Steps 3+3.5 (Sitemap + Listing)
        # These two groups have no dependency on each other.

        async def _pw_and_visual():
            """Steps 2.5 + 2.7: Playwright screenshot/colors → Gemini visual analysis."""
            if not state.pw_computed_colors and not self.should_stop():
                try:
                    result = await asyncio.to_thread(self._pw_extract_colors, state.website_url)
                    if result.get("computed_colors"):
                        state.pw_computed_colors = result["computed_colors"]
                        self.log(f"Playwright extracted {len(state.pw_computed_colors)} computed color(s)")
                    if result.get("computed_fonts"):
                        state.pw_computed_fonts = result["computed_fonts"]
                        self.log(f"Playwright extracted {len(state.pw_computed_fonts)} computed font(s)")
                    if result.get("screenshot_png") and not state.pw_screenshot:
                        state.pw_screenshot = result["screenshot_png"]

                    # SPA supplement: extract contacts, social, images, JSON-LD
                    # from JS-rendered DOM (catches data invisible in static HTML)
                    pw_html = result.get("rendered_html", "")
                    if pw_html and len(pw_html) > 500:
                        pw_soup = BeautifulSoup(pw_html, "html.parser")

                        # Supplement images from rendered DOM
                        pw_images = extract_all_images(pw_soup, state.base_url)
                        if len(pw_images) > len(state.images):
                            existing_srcs = {img.get("src") for img in state.images}
                            new_imgs = [i for i in pw_images if i.get("src") not in existing_srcs]
                            if new_imgs:
                                state.images.extend(new_imgs)
                                self.log(f"Playwright DOM added {len(new_imgs)} image(s)")

                        # Supplement JSON-LD from rendered DOM
                        pw_jsonld = extract_jsonld(pw_soup)
                        if pw_jsonld and not state.structured_data:
                            state.structured_data = pw_jsonld
                        elif pw_jsonld:
                            existing_str = {json.dumps(d, sort_keys=True) for d in state.structured_data}
                            for block in pw_jsonld:
                                if json.dumps(block, sort_keys=True) not in existing_str:
                                    state.structured_data.append(block)

                        # Supplement contacts + social from rendered DOM
                        # (SPA footers are invisible in static HTML)
                        from scraper_agents.extractors.contact_extraction import (
                            extract_social_links,
                            extract_contact_info,
                        )
                        pw_social = extract_social_links(pw_soup, state.base_url)
                        if pw_social:
                            if not hasattr(state, '_pw_social'):
                                state._pw_social = pw_social
                        pw_contact = extract_contact_info(pw_soup, state.base_url)
                        if pw_contact:
                            if not hasattr(state, '_pw_contact'):
                                state._pw_contact = pw_contact

                except Exception as e:
                    self.log(f"Playwright color extraction failed: {e}", level="warning")

            if state.pw_screenshot and not self.should_stop():
                await self._visual_analysis(state)

        async def _sitemap_and_listing():
            """Steps 3 + 3.5: Sitemap parsing → listing page discovery."""
            if self.should_stop():
                return
            from scraper_agents.extractors.product_parsing import is_product_detail_url, is_listing_url
            try:
                raw_sitemap_urls = await asyncio.wait_for(
                    asyncio.to_thread(self._parse_sitemap, state.domain),
                    timeout=30,
                )
            except asyncio.TimeoutError:
                self.log("sitemap parsing timed out after 30s", level="warning")
                raw_sitemap_urls = []
            detail_urls = []
            listing_urls = []
            for u in raw_sitemap_urls:
                if is_product_detail_url(u):
                    detail_urls.append(u)
                elif is_listing_url(u):
                    listing_urls.append(u)
            state.sitemap_urls = detail_urls
            state.listing_urls = listing_urls
            self.log(f"sitemap: {len(detail_urls)} detail URLs, {len(listing_urls)} listing URLs (from {len(raw_sitemap_urls)} total)")

            # Step 3.5: Discover listing pages from nav links + external shop domains
            if not state.sitemap_urls and not self.should_stop():
                from scraper_agents.extractors.html_helpers import domain_from_url
                site_domain = domain_from_url(state.base_url)
                nav_listing_urls = set(state.listing_urls)
                for link in state.nav_links:
                    url = link.get("url", "")
                    if not url or url in nav_listing_urls:
                        continue
                    link_domain = domain_from_url(url)
                    if link_domain and link_domain != site_domain and not link_domain.endswith("." + site_domain):
                        continue
                    if is_listing_url(url):
                        nav_listing_urls.add(url)
                        state.listing_urls.append(url)

                shop_urls = self._find_brand_shop_urls(state)
                if shop_urls:
                    state.listing_urls = shop_urls + state.listing_urls
                    self.log(f"found {len(shop_urls)} brand-affiliated shop URL(s)")

                if not state.listing_urls and not shop_urls and state.nav_products:
                    for path in ['/products/', '/shop/', '/store/', '/collection/', '/range/']:
                        candidate = state.base_url.rstrip('/') + path
                        state.listing_urls.append(candidate)
                if state.listing_urls:
                    self.log(f"discovered {len(state.listing_urls)} listing pages")

        await asyncio.gather(_pw_and_visual(), _sitemap_and_listing())

        # Step 4: Classify site + categorize links via Gemini
        # Always run — Gemini can classify from title/meta even with 0 nav_links
        if not self.should_stop():
            await self._classify_site(state)
            self.log(f"site_type={state.site_type}, categories={list(state.site_map.keys())}")

        # Step 5: Fetch + cache key pages concurrently
        if not self.should_stop() and state.deep_scrape:
            await self._cache_pages(state)
            self.log(f"cached {len(state.page_cache)} pages")

        # Step 5.5: Image-based product discovery for non-ecommerce sites.
        # Two tiers: (A) deterministic filename extraction, (B) Vision enrichment.
        _needs_image_extraction = (
            not self.should_stop()
            and state.site_type in ("restaurant", "brand", "services", "portfolio")
            and not state.sitemap_urls
        )
        if (not _needs_image_extraction
                and not self.should_stop()
                and state.visual_analysis
                and state.visual_analysis.get("image_content")):
            _needs_image_extraction = True

        if _needs_image_extraction:
            # Tier A: Deterministic filename/alt extraction (always consistent)
            self._extract_image_products(state)
            # Tier B: Vision enrichment — add prices/descriptions to existing products
            # Only runs if Tier A found products to enrich
            if state.discovered_products and not self.should_stop():
                await self._vision_enrich_products(state)

        # Step 6: Gemini content analysis — extract products/services from text
        if not self.should_stop():
            await self._analyze_content(state)

        # Step 6.5: Match product image URLs from cached page <img> tags
        # Vision/Gemini give us names but not image URLs — match by name similarity.
        self._match_product_image_urls(state)

        self.log(f"discovered {len(state.discovered_products)} products, "
                 f"{len(state.discovered_services)} services")

    # ------------------------------------------------------------------
    def _extract_image_products(self, state: ScrapeState) -> None:
        """Tier A: Deterministic product discovery from image filenames/alt text.

        Scans cached product/menu pages for ``<img>`` tags whose filenames
        or alt text look like product names (e.g., ``Pizza.webp``, ``Chai-1.webp``).
        Always returns the same results for the same HTML — fully deterministic.
        """
        product_pages = state.site_map.get("product", [])
        if not product_pages:
            return

        _SKIP = {"icon", "logo", "arrow", "chevron", "close", "menu", "search",
                 "spinner", "loader", "badge", "banner", "hero", "caret",
                 "hamburger", "facebook", "instagram", "twitter", "linkedin",
                 "youtube", "social", "play-store", "app-store", "whatsapp",
                 "bg", "background", "pattern", "texture", "gradient",
                 "placeholder", "default", "avatar", "profile", "user",
                 "footer", "header", "nav", "sidebar", "widget", "ad",
                 "tracking", "pixel", "analytics", "noscript", "blank"}

        hints: list = []
        for pi in product_pages:
            html = state.page_cache.get(pi.url)
            if not html:
                continue
            page_soup = BeautifulSoup(html, "html.parser")
            for img in page_soup.find_all("img"):
                src = (img.get("src") or "").strip()
                if not src or src.startswith("data:"):
                    continue
                if any(tp in src.lower() for tp in ["tr?id=", "pixel", "analytics", "noscript",
                                                     "facebook.com/tr", "doubleclick", "gtm"]):
                    continue
                w, h = img.get("width", ""), img.get("height", "")
                if w in ("0", "1") or h in ("0", "1"):
                    continue
                alt = (img.get("alt") or "").strip()
                filename = src.rsplit("/", 1)[-1].split("?")[0]
                name_from_file = filename.rsplit(".", 1)[0] if "." in filename else filename
                name = self._clean_image_product_name(name_from_file, alt, state.company_name, _SKIP)
                if name:
                    from scraper_agents.extractors.html_helpers import make_absolute_url
                    abs_src = make_absolute_url(src, state.base_url)
                    hints.append({"name": name, "image_url": abs_src, "source_url": pi.url})

        if not hints:
            return

        existing = {p.get("name", "").lower().strip() for p in state.discovered_products}
        added = 0
        for h in hints:
            key = h["name"].lower().strip()
            if key not in existing and len(key) > 1:
                state.discovered_products.append({
                    "name": h["name"], "description": "", "category": "",
                    "price": None, "url": h["source_url"],
                    "image_urls": [h["image_url"]], "source": "image_filename",
                })
                existing.add(key)
                added += 1
        if added:
            self.log(f"image filename extraction: {added} product hints")

    @staticmethod
    def _clean_image_product_name(
        filename: str, alt: str, company_name: str, skip_keywords: set
    ) -> Optional[str]:
        """Extract a product name from an image filename or alt text."""
        if alt and len(alt) > 2:
            alt_clean = alt.strip()
            alt_lower = alt_clean.lower()
            if alt_lower in ("image", "photo", "img", "picture", "logo", "icon"):
                pass
            elif "," in alt_clean or "?" in alt_clean or "&" in alt_clean:
                pass
            else:
                if company_name:
                    cn_lower = company_name.lower().strip()
                    if alt_lower.startswith(cn_lower):
                        alt_clean = alt_clean[len(cn_lower):].strip(" -")
                        alt_lower = alt_clean.lower()
                if not alt_clean or (company_name and alt_lower == company_name.lower().strip()):
                    pass
                elif any(kw in alt_lower for kw in skip_keywords):
                    pass
                elif len(alt_clean.split()) <= 5:
                    return alt_clean.strip()

        name = filename.replace("-", " ").replace("_", " ").strip()
        if "?" in filename or "&" in filename or "=" in filename:
            return None
        if len(name) <= 2:
            return None
        clean = name.replace(" ", "")
        if re.match(r'^[a-f0-9]{8,}$', clean, re.I):
            return None
        if re.match(r'^(img|image|photo|pic|dsc|screenshot|thumb|tn|tr|fb|wp)\s*[\d\-]*$', name.lower()):
            return None
        digits = sum(1 for c in clean if c.isdigit())
        if len(clean) > 3 and digits / len(clean) > 0.5:
            return None
        name = re.sub(r'\s+\d+$', '', name).strip()
        if not name:
            return None
        if len(name.split()) > 4:
            return None
        name_lower = name.lower()
        if any(kw in name_lower for kw in skip_keywords):
            return None
        if company_name:
            for prefix in [company_name.lower(), company_name.lower().replace(" ", " ")]:
                if name_lower.startswith(prefix):
                    name = name[len(prefix):].strip(" -")
                    if not name:
                        return None
        return name.title() if name else None

    async def _vision_enrich_products(self, state: ScrapeState) -> None:
        """Tier B: Enrich existing products with prices/descriptions via Gemini Vision.

        Screenshots the product/menu page (not homepage) and asks Gemini to
        provide prices and categories for products already discovered.
        Does NOT discover new products — only enriches existing ones.
        """
        if not state.discovered_products:
            return

        import base64
        product_names = [p.get("name", "") for p in state.discovered_products if p.get("source") == "image_filename"]
        if not product_names:
            return

        # Screenshot the product/menu page (where prices are visible)
        screenshot = None
        target_url = None
        product_pages = state.site_map.get("product", [])
        if product_pages:
            target_url = product_pages[0].url
        if not target_url and state.visual_analysis and state.visual_analysis.get("product_pages"):
            rel = state.visual_analysis["product_pages"][0]
            target_url = state.base_url.rstrip("/") + "/" + rel.lstrip("/")

        if target_url:
            from playwright.sync_api import sync_playwright

            def _take_screenshot(url: str) -> Optional[bytes]:
                pw = None
                browser = None
                try:
                    pw = sync_playwright().start()
                    browser = pw.chromium.launch(headless=True)
                    page = browser.new_page(user_agent=DEFAULT_USER_AGENT,
                                            viewport={"width": 1280, "height": 900})
                    page.goto(url, wait_until="domcontentloaded", timeout=12_000)
                    page.wait_for_timeout(2000)
                    return page.screenshot(type="png", full_page=True)
                except Exception:
                    return None
                finally:
                    try:
                        if browser: browser.close()
                        if pw: pw.stop()
                    except Exception:
                        pass

            try:
                screenshot = await asyncio.wait_for(
                    asyncio.to_thread(_take_screenshot, target_url), timeout=20)
            except Exception:
                pass

        # Fallback to homepage screenshot
        if not screenshot:
            screenshot = state.pw_screenshot
        if not screenshot:
            return

        prompt_text = (
            f"I have these product/menu items from {state.company_name or state.domain}: "
            f"{', '.join(product_names[:20])}\n\n"
            "Looking at this page screenshot, provide the PRICE and CATEGORY "
            "for each item if visible on the page.\n"
            "Use the EXACT same name I provided — do not rename items.\n"
            "Return ONLY JSON:\n"
            '{{"enrichments": [{{"name": "...(exact name from my list)", '
            '"price": "...(if visible on page, else null)", '
            '"category": "...(e.g. Beverages, Snacks, Food)", '
            '"description": "...(brief, if visible, else null)"}}]}}'
        )

        try:
            from google import genai
            b64 = base64.b64encode(screenshot).decode()
            contents = [
                {"inline_data": {"mime_type": "image/png", "data": b64}},
                prompt_text,
            ]
            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.gemini.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                ),
                timeout=15,
            )
            text = (response.text or "").strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    text = text[start:end]

            data = json.loads(text)
            enrichments = data.get("enrichments", [])

            enriched = 0
            name_map = {p.get("name", "").lower().strip(): p for p in state.discovered_products}
            for e in enrichments:
                ename = (e.get("name") or "").lower().strip()
                if ename in name_map:
                    p = name_map[ename]
                    if e.get("price") and not p.get("price"):
                        p["price"] = e["price"]
                    if e.get("category") and not p.get("category"):
                        p["category"] = e["category"]
                    if e.get("description") and not p.get("description"):
                        p["description"] = e["description"]
                    enriched += 1
                else:
                    # Fuzzy match: try partial name matching
                    for key, p in name_map.items():
                        if ename in key or key in ename:
                            if e.get("price") and not p.get("price"):
                                p["price"] = e["price"]
                            if e.get("category") and not p.get("category"):
                                p["category"] = e["category"]
                            if e.get("description") and not p.get("description"):
                                p["description"] = e["description"]
                            enriched += 1
                            break
            if enriched:
                self.log(f"vision enriched {enriched}/{len(enrichments)} products")

        except Exception as e:
            self.log(f"vision enrichment failed: {e}", level="warning")

    # ------------------------------------------------------------------
    def _match_product_image_urls(self, state: ScrapeState) -> None:
        """Match discovered products to image URLs from cached pages by name similarity.

        Products from Vision/Gemini have names but no image URLs.
        This scans all cached page ``<img>`` tags and matches by
        filename/alt-text overlap with the product name.
        """
        from scraper_agents.extractors.html_helpers import extract_all_images, make_absolute_url

        products_needing_images = [
            p for p in state.discovered_products
            if not p.get("image_urls")
        ]
        if not products_needing_images:
            return

        # Collect all candidate images from homepage + cached pages
        _SKIP_KW = {"icon", "logo", "arrow", "chevron", "close", "menu",
                     "search", "spinner", "loader", "banner", "hero",
                     "caret", "hamburger", "play-store", "app-store",
                     "facebook", "instagram", "twitter", "linkedin",
                     "youtube", "social", "tracking", "pixel", "analytics"}

        candidate_images: List[Dict] = []
        # Homepage images
        for img in (state.images or []):
            src = (img.get("src") or "").lower()
            if src and not src.endswith(".svg") and not any(kw in src for kw in _SKIP_KW):
                candidate_images.append(img)
        # Images from all cached pages
        for cache_url, cache_html in state.page_cache.items():
            try:
                page_soup = BeautifulSoup(cache_html, "html.parser")
                page_images = extract_all_images(page_soup, cache_url, limit=50)
                for img in page_images:
                    src = (img.get("src") or "").lower()
                    if src and not src.endswith(".svg") and not any(kw in src for kw in _SKIP_KW):
                        candidate_images.append(img)
            except Exception:
                pass

        if not candidate_images:
            return

        # Company name words to exclude (match everything)
        company_words = set()
        if state.company_name:
            company_words = set(re.findall(r'[a-z]{4,}', state.company_name.lower()))

        matched = 0
        for product in products_needing_images:
            pname = (product.get("name") or "").lower().strip()
            if not pname or len(pname) < 3:
                continue

            # Use 4+ char words to avoid false matches on "tea", "ice", etc.
            pname_words = set(re.findall(r'[a-z]{4,}', pname)) - company_words

            best_url = None
            best_score = 0.0

            for img in candidate_images:
                img_alt = (img.get("alt") or "").lower()
                img_src = (img.get("src") or "").lower()
                fn = img_src.rsplit("/", 1)[-1].split("?")[0] if "/" in img_src else img_src
                fn_clean = fn.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").lower()
                fn_clean = re.sub(r'\s+\d+$', '', fn_clean)  # strip trailing numbers

                score = 0.0

                if pname_words:
                    # Word-overlap matching (4+ char words)
                    alt_words = set(re.findall(r'[a-z]{4,}', img_alt))
                    fn_words = set(re.findall(r'[a-z]{4,}', fn_clean))
                    alt_overlap = len(pname_words & alt_words) / len(pname_words)
                    fn_overlap = len(pname_words & fn_words) / len(pname_words)
                    score = max(alt_overlap, fn_overlap)
                else:
                    # Product name has only short words (e.g., "Ice Tea", "Momo")
                    # Use exact substring match on filename
                    pname_slug = pname.replace(" ", "-")
                    pname_slug2 = pname.replace(" ", " ")
                    if pname_slug in fn_clean.replace(" ", "-") or pname in fn_clean:
                        score = 1.0

                # Single-word products need exact match; multi-word need 50%
                min_score = 1.0 if (pname_words and len(pname_words) == 1) else 0.5
                if not pname_words:
                    min_score = 1.0  # exact substring match required

                if score >= min_score and score > best_score:
                    best_score = score
                    best_url = img.get("src")

            if best_url:
                product["image_urls"] = [best_url]
                matched += 1

        if matched:
            self.log(f"matched {matched} product image URLs from page <img> tags")

    # ------------------------------------------------------------------
    @staticmethod
    def _pw_extract_colors(url: str) -> dict:
        """Run Playwright briefly to extract computed CSS colors + screenshot."""
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
            page.goto(url, wait_until="domcontentloaded",
                      timeout=TIMEOUTS["page_load_ms"])
            page.wait_for_timeout(TIMEOUTS["page_render_wait_ms"])
            try:
                computed_colors = page.evaluate(_PW_COLOR_JS)
            except Exception:
                computed_colors = []
            try:
                computed_fonts = page.evaluate(_PW_FONT_JS) if hasattr(page, 'evaluate') else []
            except Exception:
                computed_fonts = []
            try:
                screenshot = page.screenshot(type="png", full_page=False)
            except Exception:
                screenshot = None
            # Capture rendered DOM HTML for SPA supplement (contacts, images, JSON-LD)
            try:
                rendered_html = page.content()
            except Exception:
                rendered_html = ""
            browser.close()
            return {
                "computed_colors": computed_colors,
                "computed_fonts": computed_fonts,
                "screenshot_png": screenshot,
                "rendered_html": rendered_html,
            }
        finally:
            pw.stop()

    # ------------------------------------------------------------------
    async def _fetch_homepage(self, state: ScrapeState) -> Optional[str]:
        """Fetch homepage — HTTP first, Playwright fallback, domain-root fallback."""
        html = await self._try_fetch_url(state.website_url, state)
        if html:
            return html

        # If user-provided URL has a path and failed, try the domain root
        parsed = urlparse(state.website_url)
        if parsed.path not in ("", "/", "/index.html"):
            self.log(f"subpage failed, trying domain root: {state.base_url}")
            html = await self._try_fetch_url(state.base_url, state)
            if html:
                # Cache the original user URL for later content analysis
                # (it may work via page caching with different headers/timing)
                self.log(f"using {state.base_url} as homepage (subpage unavailable)")
                return html

        return None

    async def _visual_analysis(self, state: ScrapeState) -> None:
        """Analyze homepage screenshot with Gemini Vision for navigation mapping,
        image-embedded content detection, and layout intelligence."""
        import base64

        from scraper_agents.prompts.visual_analysis import VISUAL_ANALYSIS_PROMPT

        nav_text = "\n".join(
            f"- {l.get('text', '')}: {l.get('url', '')}"
            for l in state.nav_links[:25]
        ) or "(no nav links found)"

        prompt_text = VISUAL_ANALYSIS_PROMPT.format(
            company_name=state.company_name or state.company_name_hint or state.domain,
            domain=state.domain,
            nav_links_text=nav_text,
        )

        try:
            from google import genai

            b64_screenshot = base64.b64encode(state.pw_screenshot).decode()
            contents = [
                {"inline_data": {"mime_type": "image/png", "data": b64_screenshot}},
                prompt_text,
            ]

            response = await asyncio.wait_for(
                asyncio.to_thread(
                    self.gemini.models.generate_content,
                    model=self.model,
                    contents=contents,
                    config=genai.types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type="application/json",
                    ),
                ),
                timeout=TIMEOUTS.get("visual_analysis", 15),
            )

            text = (response.text or "").strip()
            # Strip markdown fences if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    text = text[start:end]

            data = json.loads(text)
            state.visual_analysis = data

            self.log(
                f"visual analysis: nav_mapping={len(data.get('nav_mapping', {}))}, "
                f"image_content={len(data.get('image_content', []))}, "
                f"site_type_hint={data.get('site_type_hint')}"
            )

            # Add visually-identified product pages to listing_urls
            for rel_path in data.get("product_pages", []):
                abs_url = state.base_url.rstrip("/") + "/" + rel_path.lstrip("/")
                if abs_url not in state.listing_urls:
                    state.listing_urls.append(abs_url)
                    self.log(f"visual analysis added listing URL: {abs_url}")

        except asyncio.TimeoutError:
            self.log("visual analysis timed out", level="warning")
        except json.JSONDecodeError as e:
            self.log(f"visual analysis JSON parse failed: {e}", level="warning")
        except Exception as e:
            self.log(f"visual analysis failed: {e}", level="warning")

    async def _try_fetch_url(self, url: str, state: ScrapeState) -> Optional[str]:
        """Try fetching a URL via HTTP, then Playwright fallback."""
        try:
            resp = await asyncio.to_thread(
                requests.get,
                url,
                headers=DEFAULT_HEADERS,
                timeout=TIMEOUTS["http_request"],
                allow_redirects=True,
            )
            resp.encoding = "utf-8"
            if resp.status_code == 200:
                html = resp.text
                if len(html) > 500:
                    self.log(f"HTTP 200 {url[:80]}, {len(html)} chars")
                    return html
                self.log(f"HTTP 200 but only {len(html)} chars — trying Playwright")
            else:
                self.log(f"HTTP {resp.status_code} for {url[:80]} — trying Playwright", level="warning")
        except Exception as e:
            self.log(f"HTTP request failed for {url[:80]}: {e} — trying Playwright", level="warning")

        # Playwright fallback for this specific URL
        return await self._fetch_url_with_playwright(url, state)

    async def _fetch_url_with_playwright(self, url: str, state: ScrapeState) -> Optional[str]:
        """Playwright fallback — also captures screenshot + computed colors."""
        def _render(target_url: str) -> dict:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            try:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(user_agent=DEFAULT_USER_AGENT)
                page.goto(target_url, wait_until="domcontentloaded",
                          timeout=TIMEOUTS["page_load_ms"])
                page.wait_for_timeout(TIMEOUTS["page_render_wait_ms"])
                html = page.content()
                try:
                    computed_colors = page.evaluate(_PW_COLOR_JS)
                except Exception:
                    computed_colors = []
                try:
                    screenshot = page.screenshot(type="png", full_page=False)
                except Exception:
                    screenshot = None
                browser.close()
                return {"html": html, "computed_colors": computed_colors,
                        "screenshot_png": screenshot}
            finally:
                pw.stop()

        try:
            result = await asyncio.to_thread(_render, url)
            html = result.get("html")
            # Store Playwright artifacts (only from first successful fetch)
            if not state.pw_computed_colors:
                state.pw_computed_colors = result.get("computed_colors", [])
            if not state.pw_screenshot:
                state.pw_screenshot = result.get("screenshot_png")

            # Check for bot-rejection pages
            if html and any(sig in html.lower() for sig in
                           ["403 forbidden", "access denied", "checking your browser",
                            "enable javascript", "cloudflare", "ray id:"]):
                self.log(f"Playwright got bot-rejection page for {url[:80]}", level="warning")
                return None
            if html:
                self.log(f"Playwright: {len(html)} chars for {url[:80]}")
            return html
        except ImportError:
            self.log("Playwright not installed", level="warning")
            return None
        except Exception as e:
            self.log(f"Playwright failed for {url[:80]}: {e}", level="warning")
            return None

    # ------------------------------------------------------------------
    def _parse_sitemap(self, domain: str) -> List[str]:
        """Parse robots.txt → sitemap.xml → extract product URLs."""
        import time as _time
        product_urls: List[str] = []
        sitemap_urls: List[str] = []
        _deadline = _time.monotonic() + 25  # 25s hard limit inside thread

        # 1. Fetch robots.txt for sitemap pointers
        try:
            robots_resp = requests.get(
                f"https://{domain}/robots.txt",
                headers=DEFAULT_HEADERS,
                timeout=TIMEOUTS["sitemap_fetch"],
            )
            if robots_resp.status_code == 200:
                for line in robots_resp.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm_url = line.split(":", 1)[1].strip()
                        if sm_url:
                            sitemap_urls.append(sm_url)
        except Exception:
            pass

        if not sitemap_urls:
            # Try common sitemap paths
            for path in ["/sitemap.xml", "/sitemap_index.xml"]:
                sitemap_urls.append(f"https://{domain}{path}")

        # 2. Recursively parse sitemaps
        visited: set = set()
        for sm_url in sitemap_urls[:5]:
            self._parse_sitemap_xml(sm_url, product_urls, visited, deadline=_deadline)
            if len(product_urls) >= 500:
                break

        return product_urls[:500]

    def _parse_sitemap_xml(self, url: str, product_urls: List[str],
                           visited: set, depth: int = 0,
                           deadline: float = 0) -> None:
        import time as _time
        if depth > 2 or url in visited:
            return
        if deadline and _time.monotonic() > deadline:
            return
        if len(product_urls) >= 500:
            return
        visited.add(url)
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS,
                                timeout=TIMEOUTS["sitemap_fetch"])
            if resp.status_code != 200:
                return
            root = ET.fromstring(resp.content)
            ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # Sitemap index → recurse (skip non-English locale sitemaps)
            for sitemap in root.findall(".//sm:sitemap/sm:loc", ns)[:10]:
                if deadline and _time.monotonic() > deadline:
                    break
                if sitemap.text:
                    child_url = sitemap.text.strip()
                    if LOCALE_PATH_RE.search(urlparse(child_url).path):
                        continue
                    self._parse_sitemap_xml(child_url, product_urls,
                                            visited, depth + 1, deadline)

            # URL set → check for product patterns (skip non-English locale URLs)
            for loc in root.findall(".//sm:url/sm:loc", ns):
                if loc.text:
                    page_url = loc.text.strip()
                    if LOCALE_PATH_RE.search(urlparse(page_url).path):
                        continue
                    if any(pat in page_url.lower() for pat in PRODUCT_URL_PATTERNS):
                        product_urls.append(page_url)
        except Exception:
            pass

    # ------------------------------------------------------------------
    async def _classify_site(self, state: ScrapeState) -> None:
        """Use Gemini to classify site type and categorize nav links."""
        nav_text = "\n".join(
            f"- {l['text']}: {l['url']}" for l in state.nav_links[:30]
        )
        # When no nav links, supplement with headings so Gemini has more context
        if not nav_text and state.headings:
            headings_text = "\n".join(
                f"- [{h['level']}] {h['text']}" for h in state.headings[:20]
            )
            nav_text = f"(no nav links found — page headings for context:\n{headings_text})"
        # Inject visual analysis context if available
        visual_context = ""
        if state.visual_analysis:
            va = state.visual_analysis
            if va.get("site_type_hint"):
                visual_context += f"\nVisual analysis of the screenshot suggests site type: {va['site_type_hint']}"
            if va.get("nav_mapping"):
                mapping_text = ", ".join(f'"{k}"={v}' for k, v in va["nav_mapping"].items())
                visual_context += f"\nVisual nav mapping: {mapping_text}"
            if va.get("image_content"):
                visual_context += f"\nVisual observations: {'; '.join(va['image_content'][:3])}"
        prompt = SITE_CLASSIFICATION_PROMPT.format(
            title=state.title,
            meta_description=state.meta_description[:500],
            domain=state.domain,
            nav_links_text=nav_text or "(no nav links found)",
            visual_context=visual_context,
        )

        try:
            from google import genai
            response = await asyncio.to_thread(
                self.gemini.models.generate_content,
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            # Strip markdown fences + extract JSON substring
            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    text = text[start:end]
            data = json.loads(text)

            state.site_type = data.get("site_type", "brand")
            state.company_name = data.get("company_name", "") or state.company_name_hint or state.domain

            for link_info in data.get("links", []):
                cat = link_info.get("category", "other")
                pi = PageInfo(
                    url=link_info.get("url", ""),
                    title=link_info.get("text", ""),
                    category=cat,
                    priority=link_info.get("priority", 3),
                )
                state.site_map.setdefault(cat, []).append(pi)

        except Exception as e:
            self.log(f"Gemini site classification failed: {e}", level="warning")
            # Fallback: keyword-based classification
            self._fallback_classify(state)

    @staticmethod
    def _find_brand_shop_urls(state: ScrapeState) -> list:
        """Detect brand-affiliated external shop domains in nav/footer links.

        Brand sites often link to a separate e-commerce domain that shares
        the company name (e.g. dabur.com → daburshop.com).  These are NOT
        random external links — they're brand-owned storefronts.

        Returns a list of shop URLs to add to ``state.listing_urls``.
        """
        from scraper_agents.extractors.product_parsing import is_listing_url
        from scraper_agents.extractors.html_helpers import domain_from_url

        # Build company slug — strip TLD from domain to avoid "daburcom"
        name_source = (
            state.company_name
            or state.company_name_hint
            or (state.domain.split(".")[0] if state.domain else "")
        )
        company_slug = re.sub(r"[^a-z0-9]", "", name_source.lower())
        if not company_slug or len(company_slug) < 3:
            return []

        site_domain = domain_from_url(state.base_url)
        shop_keywords = {"shop", "store", "buy", "order", "ecommerce"}
        existing = set(state.listing_urls)
        found: list = []

        # Scan ALL nav links (not just nav_products — the shop link might
        # be labeled "Shop Now" or "Buy Online", not a product name)
        for link in state.nav_links:
            url = link.get("url", "")
            if not url or "://" not in url:
                continue
            link_domain = domain_from_url(url)
            if not link_domain or link_domain == site_domain:
                continue  # same domain, not what we're looking for

            # Brand-affiliated check: domain must contain company slug
            domain_bare = link_domain.replace(".", "")
            if company_slug not in domain_bare:
                continue

            # Must look like a shop or listing page
            link_text = (link.get("text") or "").lower()
            domain_has_shop = any(kw in link_domain for kw in shop_keywords)
            text_has_shop = any(kw in link_text for kw in shop_keywords)
            url_is_listing = is_listing_url(url)

            if domain_has_shop or text_has_shop or url_is_listing:
                # Strip UTM params and normalize
                clean_url = url.split("?")[0].rstrip("/")
                if clean_url not in existing:
                    found.append(clean_url)
                    existing.add(clean_url)
                # For shop homepages, also add common collection/product paths
                # so ProductAgent can find actual product listings
                shop_base = f"https://{link_domain}"
                for path in ["/collections/all", "/products", "/collections"]:
                    cand = shop_base + path
                    if cand not in existing:
                        found.append(cand)
                        existing.add(cand)

        # Also check the homepage soup for <a> tags outside nav
        # (footer "Shop Online" links etc.)
        if not found and state.homepage_soup:
            for a_tag in state.homepage_soup.find_all("a", href=True):
                href = (a_tag.get("href") or "").strip()
                if not href or "://" not in href:
                    continue
                link_domain = domain_from_url(href)
                if not link_domain or link_domain == site_domain:
                    continue
                domain_bare = link_domain.replace(".", "")
                if company_slug not in domain_bare:
                    continue
                domain_has_shop = any(kw in link_domain for kw in shop_keywords)
                url_is_listing = is_listing_url(href)
                if domain_has_shop or url_is_listing:
                    clean_url = href.split("?")[0].rstrip("/")
                    if clean_url not in existing:
                        found.append(clean_url)
                        existing.add(clean_url)
                    shop_base = f"https://{link_domain}"
                    for path in ["/collections/all", "/products", "/collections"]:
                        cand = shop_base + path
                        if cand not in existing:
                            found.append(cand)
                            existing.add(cand)
                    break  # one shop URL is enough from body scan

        return found

    def _fallback_classify(self, state: ScrapeState) -> None:
        """Keyword-based fallback when Gemini classification fails."""
        state.site_type = "brand"
        _KW_MAP = {
            "product": ["product", "shop", "store", "catalog", "menu", "pricing", "buy"],
            "about": ["about", "story", "team", "who we are", "company"],
            "service": ["service", "solution", "offering", "what we do"],
            "blog": ["blog", "news", "article", "insight", "resource", "press"],
            "contact": ["contact", "support", "help", "get in touch", "location"],
            "gallery": ["gallery", "portfolio", "case stud", "our work", "project"],
            "careers": ["career", "job", "hiring", "join us", "work with us"],
        }
        for link in state.nav_links:
            text_lower = (link.get("text", "") + " " + link.get("href", "")).lower()
            matched = False
            for cat, keywords in _KW_MAP.items():
                if any(kw in text_lower for kw in keywords):
                    pi = PageInfo(url=link["url"], title=link.get("text", ""), category=cat, priority=3)
                    state.site_map.setdefault(cat, []).append(pi)
                    matched = True
                    break
            if not matched:
                pi = PageInfo(url=link["url"], title=link.get("text", ""), category="other", priority=5)
                state.site_map.setdefault("other", []).append(pi)

        # When no nav_links, infer site_type from title/meta/headings
        if not state.nav_links:
            combined = f"{state.title} {state.meta_description}".lower()
            heading_text = " ".join(h.get("text", "") for h in state.headings[:20]).lower()
            combined += " " + heading_text
            if any(kw in combined for kw in ["delivery platform", "marketplace", "aggregator", "book a ride", "food delivery"]):
                state.site_type = "platform"
            elif any(kw in combined for kw in ["group", "conglomerate", "holding company", "our businesses", "our companies", "subsidiaries", "portfolio of companies"]):
                state.site_type = "conglomerate"
            elif any(kw in combined for kw in ["order", "delivery", "shop", "buy", "cart", "price"]):
                state.site_type = "ecommerce"
            elif any(kw in combined for kw in ["menu", "restaurant", "food", "dine", "reservation"]):
                state.site_type = "restaurant"
            elif any(kw in combined for kw in ["service", "consult", "agency", "solution"]):
                state.site_type = "services"

        # Infer site_type from available categories
        if state.sitemap_urls or state.site_map.get("product"):
            state.site_type = "ecommerce"
        elif state.site_map.get("service"):
            state.site_type = "services"
        if not state.company_name:
            state.company_name = state.company_name_hint or state.domain

    # ------------------------------------------------------------------
    async def _cache_pages(self, state: ScrapeState) -> None:
        """Fetch and cache key pages concurrently."""
        # Collect URLs to fetch, prioritized
        pages_to_fetch: List[str] = []
        for cat in state.site_map:
            for pi in state.site_map[cat]:
                if pi.url and pi.url not in state.page_cache:
                    pages_to_fetch.append(pi.url)

        pages_to_fetch = pages_to_fetch[:CONCURRENCY["max_cached_pages"]]
        if not pages_to_fetch:
            return

        def _fetch_page(page_url: str) -> tuple:
            try:
                resp = requests.get(page_url, headers=DEFAULT_HEADERS,
                                    timeout=TIMEOUTS["http_request"])
                if resp.status_code == 200:
                    return (page_url, resp.text)
            except Exception:
                pass
            return (page_url, None)

        results = await asyncio.to_thread(self._fetch_pages_parallel, pages_to_fetch)
        for page_url, html in results:
            if html:
                state.page_cache[page_url] = html

        # Extract about_content from cached about pages
        for pi in state.site_map.get("about", []):
            if pi.url in state.page_cache:
                about_soup = BeautifulSoup(state.page_cache[pi.url], "html.parser")
                for tag in about_soup.find_all(["script", "style", "nav", "footer"]):
                    tag.decompose()
                state.about_content = about_soup.get_text(separator=" ", strip=True)[:5000]
                break

    def _fetch_pages_parallel(self, urls: List[str]) -> List[tuple]:
        results = []
        with ThreadPoolExecutor(max_workers=CONCURRENCY["page_cache_workers"]) as pool:
            futures = {pool.submit(self._fetch_single, u): u for u in urls}
            for future in as_completed(futures, timeout=max(5, self.time_remaining())):
                try:
                    results.append(future.result(timeout=5))
                except Exception:
                    results.append((futures[future], None))
        return results

    @staticmethod
    def _fetch_single(url: str) -> tuple:
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS,
                                timeout=TIMEOUTS["http_request"])
            if resp.status_code == 200:
                return (url, resp.text)
        except Exception:
            pass
        return (url, None)

    # ------------------------------------------------------------------
    async def _analyze_content(self, state: ScrapeState) -> None:
        """Extract products/services — nav dropdown → JSON-LD → Gemini (always) → cross-validate."""

        # === Priority 0: Navigation dropdown products ===
        seen_names: set = set()
        is_taxonomy = nav_products_are_taxonomy(state.nav_products) if state.nav_products else False
        is_verticals = nav_products_are_verticals(state.nav_products) if state.nav_products else False

        if is_verticals:
            # Store verticals separately — these are audience segments, not products
            state.nav_verticals = [p.get("name", "") for p in state.nav_products]
            self.log(f"nav items are audience verticals ({len(state.nav_verticals)}), skipping as products")

        nav_product_count = 0
        if len(state.nav_products) >= 3 and not is_taxonomy and not is_verticals:
            for np in state.nav_products:
                key = np["name"].lower().strip()
                if key not in seen_names:
                    seen_names.add(key)
                    state.discovered_products.append({
                        "name": np["name"],
                        "url": np.get("url", ""),
                        "description": "",
                        "category": "",
                        "price": None,
                        "source": "nav",
                    })
            nav_product_count = len(state.discovered_products)
            self.log(f"nav dropdown: {nav_product_count} products")

        # === Priority 1: JSON-LD structured data (website's own declared data) ===
        jsonld_products: List[Dict] = []

        # Homepage JSON-LD (already parsed in Step 2)
        if state.structured_data:
            jsonld_products.extend(extract_jsonld_products(state.structured_data))

        # JSON-LD from cached pages too
        for cache_url, cache_html in state.page_cache.items():
            try:
                page_soup = BeautifulSoup(cache_html, "html.parser")
                page_jsonld = extract_jsonld(page_soup)
                if page_jsonld:
                    jsonld_products.extend(extract_jsonld_products(page_jsonld))
            except Exception:
                pass

        # Deduplicate JSON-LD products by name (merge into existing nav products)
        added_jsonld = 0
        for p in jsonld_products:
            key = p.get("name", "").lower().strip()
            if key and key not in seen_names:
                seen_names.add(key)
                p["source"] = "jsonld"
                state.discovered_products.append(p)
                added_jsonld += 1

        if added_jsonld:
            self.log(f"JSON-LD: {added_jsonld} products from structured data")

        # === Priority 2: Gemini text analysis — ALWAYS runs for validation ===
        # Even when nav/JSON-LD found products, Gemini cross-validates
        # by reading actual page content. This catches cases where nav items
        # are NOT real products (app store listings, subsection headers, etc.).
        gemini_products: List[Dict] = []
        gemini_services: List[Dict] = []
        if not self.should_stop():
            gemini_products, gemini_services = await self._gemini_content_analysis(state)

        # === Priority 3: Cross-validate nav products against Gemini results ===
        nav_sourced = [p for p in state.discovered_products if p.get("source") == "nav"]
        if nav_sourced and gemini_products:
            gemini_name_words = []
            for gp in gemini_products:
                words = set(re.findall(r'[a-z]{3,}', gp.get("name", "").lower()))
                gemini_name_words.append(words)

            nav_confirmed = 0
            for np in nav_sourced:
                np_words = set(re.findall(r'[a-z]{3,}', np.get("name", "").lower()))
                if not np_words:
                    continue
                for gw in gemini_name_words:
                    if np_words & gw:  # at least one word overlap
                        nav_confirmed += 1
                        break

            confirmation_rate = nav_confirmed / len(nav_sourced) if nav_sourced else 0
            self.log(f"cross-validation: Gemini confirmed {nav_confirmed}/{len(nav_sourced)} nav products ({confirmation_rate:.0%})")

            if confirmation_rate < 0.3:
                # Gemini strongly disagrees — demote nav products
                state.discovered_products = [p for p in state.discovered_products if p.get("source") != "nav"]
                self.log(f"nav products demoted — replacing with Gemini results")

        # Merge Gemini text-analysis products into discovered_products.
        # If Vision already found 5+ products, only enrich existing ones
        # (don't add new text-analysis products — they tend to hallucinate
        # on image-heavy sites like restaurant menus).
        vision_count = sum(1 for p in state.discovered_products if p.get("source") == "vision")
        add_new_from_text = vision_count < 5  # only add new if Vision found few

        if gemini_products:
            existing_names = {p.get("name", "").lower().strip() for p in state.discovered_products}
            for gp in gemini_products:
                # Normalize source_url → url
                if gp.get("source_url") and not gp.get("url"):
                    gp["url"] = gp.pop("source_url")
                gp_name = gp.get("name", "").lower().strip()
                if gp_name and gp_name not in existing_names and add_new_from_text:
                    gp["source"] = "gemini"
                    state.discovered_products.append(gp)
                    existing_names.add(gp_name)
                elif gp_name in existing_names:
                    # Always enrich existing products with price/desc/url from text
                    for ep in state.discovered_products:
                        if ep.get("name", "").lower().strip() == gp_name:
                            if not ep.get("price") and gp.get("price"):
                                ep["price"] = gp["price"]
                            if not ep.get("description") and gp.get("description"):
                                ep["description"] = gp["description"]
                            if not ep.get("url") and gp.get("url"):
                                ep["url"] = gp["url"]
                            break

        if gemini_services:
            for gs in gemini_services:
                if gs.get("source_url") and not gs.get("url"):
                    gs["url"] = gs.pop("source_url")
                # Normalize image_url → image_urls
                img = gs.pop("image_url", None)
                if img and not gs.get("image_urls"):
                    gs["image_urls"] = [img]
            state.discovered_services = gemini_services

        # === Enrich products with image URLs from page images ===
        self._match_product_images(state)

    def _match_product_images(self, state: ScrapeState) -> None:
        """Match discovered products against page <img> tags by name similarity.

        Also picks up ``image_url`` returned by Gemini content analysis.
        Images are collected from the homepage AND all cached pages.
        """
        # ── Step A: Populate image_urls from Gemini's image_url field ────
        for product in state.discovered_products:
            img = product.pop("image_url", None)
            if img and not product.get("image_urls"):
                product["image_urls"] = [img]

        # ── Step B: Collect candidate images from homepage + cached pages ─
        _SKIP_KEYWORDS = {"icon", "logo", "arrow", "chevron", "close", "menu",
                          "search", "language", "flag", "spinner", "loader",
                          "instagram", "facebook", "twitter", "linkedin", "youtube",
                          "tiktok", "social", "badge", "banner", "hero", "gartner",
                          "caret", "hamburger", "play-store", "app-store",
                          "carousel", "gallery", "slider", "slideshow"}

        candidate_images = []
        # Homepage images
        for img in (state.images or []):
            src = (img.get("src") or "").lower()
            if not src or src.endswith(".svg"):
                continue
            if any(kw in src for kw in _SKIP_KEYWORDS):
                continue
            w = img.get("width") or 0
            h = img.get("height") or 0
            if w and h and w > 3 * h:
                continue
            candidate_images.append(img)

        # Images from cached pages (product/menu pages often have the images)
        for cache_url, cache_html in state.page_cache.items():
            try:
                from scraper_agents.extractors.html_helpers import extract_all_images
                page_soup = BeautifulSoup(cache_html, "html.parser")
                page_images = extract_all_images(page_soup, cache_url, limit=50)
                for img in page_images:
                    src = (img.get("src") or "").lower()
                    if not src or src.endswith(".svg"):
                        continue
                    if any(kw in src for kw in _SKIP_KEYWORDS):
                        continue
                    candidate_images.append(img)
            except Exception:
                pass

        if not candidate_images or not state.discovered_products:
            return

        # Derive company name words to exclude from matching
        company_words = set()
        if state.company_name:
            company_words = set(re.findall(r'[a-z]{3,}', state.company_name.lower()))

        matched = 0
        for product in state.discovered_products:
            if product.get("image_urls"):
                continue

            pname = (product.get("name") or "").lower().strip()
            if not pname or len(pname) < 3:
                continue

            pname_words = set(re.findall(r'[a-z]{3,}', pname)) - company_words
            if not pname_words:
                continue

            # For single-word products, require exact match in alt/src
            min_score = 1.0 if len(pname_words) == 1 else 0.5

            best_url = None
            best_score = 0

            for img in candidate_images:
                img_alt = (img.get("alt") or "").lower()
                img_src = (img.get("src") or "").lower()

                alt_words = set(re.findall(r'[a-z]{3,}', img_alt))
                overlap = pname_words & alt_words
                score = len(overlap) / len(pname_words) if pname_words else 0

                if score < min_score:
                    fn = img_src.rsplit("/", 1)[-1] if "/" in img_src else img_src
                    src_words = set(re.findall(r'[a-z]{3,}', fn))
                    src_overlap = pname_words & src_words
                    src_score = len(src_overlap) / len(pname_words) if pname_words else 0
                    score = max(score, src_score)

                if score >= min_score and score > best_score:
                    best_score = score
                    best_url = img.get("src")

            if best_url:
                product["image_urls"] = [best_url]
                matched += 1

        if matched:
            self.log(f"matched {matched} product images from page <img> tags")

    async def _gemini_content_analysis(
        self, state: ScrapeState
    ) -> tuple:
        """Gemini fallback: extract products/services from page text excerpts.

        Returns (products_list, services_list).
        """
        excerpts = []
        if state.full_text:
            excerpts.append(f"[Homepage] {state.title}\n{state.full_text[:3000]}")

        # Add up to 5 cached pages (prefer product/service categories)
        priority_cats = ["product", "service", "other"]
        added_urls: set = set()
        for cat in priority_cats:
            for pi in state.site_map.get(cat, []):
                if len(added_urls) >= 5:
                    break
                html = state.page_cache.get(pi.url)
                if not html or pi.url in added_urls:
                    continue
                added_urls.add(pi.url)
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)[:2000]
                if text:
                    excerpts.append(f"[{pi.category}: {pi.url}]\n{text}")

        # Fill remaining slots from any cached page
        if len(added_urls) < 5:
            for url, html in state.page_cache.items():
                if len(added_urls) >= 5:
                    break
                if url in added_urls:
                    continue
                added_urls.add(url)
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup.find_all(["script", "style", "nav", "footer", "header"]):
                    tag.decompose()
                text = soup.get_text(separator=" ", strip=True)[:2000]
                if text:
                    excerpts.append(f"[Page: {url}]\n{text}")

        if not excerpts:
            return [], []

        # Build visual context hint from visual analysis
        visual_context = ""
        if state.visual_analysis:
            va = state.visual_analysis
            if va.get("image_content"):
                visual_context += (
                    "\nIMPORTANT: Visual analysis detected business content embedded in images: "
                    + "; ".join(va["image_content"])
                    + "\nSome products/menu items may only appear in images, not in the HTML text. "
                    "Extract what you can infer from surrounding context, headings, and page structure."
                )
            if va.get("nav_mapping"):
                mapping = ", ".join(f'"{k}"={v}' for k, v in va["nav_mapping"].items())
                visual_context += f"\nNavigation mapping from visual analysis: {mapping}"

        prompt = CONTENT_ANALYSIS_PROMPT.format(
            company_name=state.company_name or state.domain,
            website_url=state.website_url,
            site_type=state.site_type or "unknown",
            page_excerpts="\n\n---\n\n".join(excerpts),
            visual_context=visual_context,
        )

        try:
            from google import genai

            response = await asyncio.to_thread(
                self.gemini.models.generate_content,
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            text = response.text or ""
            text = text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            if not text.startswith("{"):
                start = text.find("{")
                end = text.rfind("}") + 1
                if start != -1 and end > start:
                    text = text[start:end]

            data = json.loads(text)
            return data.get("products", []), data.get("services", [])

        except Exception as e:
            self.log(f"Gemini content analysis failed: {e}", level="warning")
            return [], []
