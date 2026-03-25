"""
ProductAgent — extracts products and services with verified images.

Adapts strategy based on site_type from CrawlerAgent.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from scraper_agents.agents.base import BaseAgent
from scraper_agents.config import (
    CONCURRENCY,
    DEFAULT_HEADERS,
    LOCALE_PATH_RE,
    PRODUCT_IMAGE_MAX_ASPECT_RATIO,
    PRODUCT_IMAGE_REJECT_PATTERNS,
    TIMEOUTS,
)
from scraper_agents.state import ScrapeState

logger = logging.getLogger(__name__)


class ProductAgent(BaseAgent):
    agent_name = "products"

    async def run(self, state: ScrapeState) -> None:
        # For SaaS / services sites with nav-dropdown products, skip
        # expensive sitemap scraping — the nav dropdown already provides the
        # authoritative, concise product list via CrawlerAgent.
        # Brand/e-commerce sites are excluded: their navs list categories, not products.
        from scraper_agents.extractors.html_helpers import nav_products_are_taxonomy, nav_products_are_verticals
        nav_authoritative = (
            len(state.nav_products) >= 3
            and state.site_type in ("saas", "services")
            and not nav_products_are_taxonomy(state.nav_products)
            and not nav_products_are_verticals(state.nav_products)
        )

        # Strategy 1: Sitemap-based product detail scraping (most reliable for e-commerce)
        if state.sitemap_urls and not nav_authoritative:
            self.log(f"sitemap has {len(state.sitemap_urls)} product detail URLs")
            products = await self._scrape_from_sitemap(state)
            if products:
                state.products = products
                self._normalize_image_fields(state.products)
                self.log(f"extracted {len(products)} products from sitemap")

        # Strategy 1.5: Listing page crawling (category/shop pages → product cards)
        # Skip for SaaS/services with authoritative nav — their listing pages have features, not products
        # Also run if sitemap products have poor image coverage (<30%) — listing pages
        # yield curated, current products with images (e.g. BenQ category pages)
        _sitemap_low_quality = False
        if state.products and state.listing_urls:
            self._normalize_image_fields(state.products)
            with_imgs = sum(1 for p in state.products if p.get("image_urls"))
            img_coverage = with_imgs / len(state.products) if state.products else 0
            if img_coverage < 0.30 and len(state.products) >= 10:
                _sitemap_low_quality = True
                self.log(f"sitemap image coverage {img_coverage:.0%} — supplementing with listing pages")

        if (not state.products or _sitemap_low_quality) and state.listing_urls and not nav_authoritative and not self.should_stop():
            self.log(f"crawling {len(state.listing_urls)} listing pages")
            listing_products = await self._scrape_from_listing_pages(state)
            if listing_products:
                self._normalize_image_fields(listing_products)
                if state.products:
                    # Merge: listing products enrich/override existing by name match,
                    # then append any new ones. No products are thrown away.
                    existing_names = {p.get("name", "").lower().strip() for p in state.products}
                    new_products = [p for p in listing_products if p.get("name", "").lower().strip() not in existing_names]
                    if _sitemap_low_quality:
                        # Sitemap products were poor — prefer listing versions
                        kept = [p for p in state.products if p.get("image_urls")]
                        state.products = kept + new_products
                    else:
                        state.products.extend(new_products)
                    state.products = self._deduplicate(state.products)
                else:
                    # No prior products — merge listing with CrawlerAgent discovered
                    discovered = list(state.discovered_products) if state.discovered_products else []
                    self._normalize_image_fields(discovered)
                    # Listing products override discovered ones by name (better data)
                    listing_names = {p.get("name", "").lower().strip() for p in listing_products}
                    extra_discovered = [p for p in discovered if p.get("name", "").lower().strip() not in listing_names]
                    state.products = listing_products + extra_discovered
                    state.products = self._deduplicate(state.products)
                self._normalize_image_fields(state.products)
                self.log(f"extracted {len(listing_products)} products from listing pages")

        # Always assign CrawlerAgent discovered services (regardless of product strategy)
        if state.discovered_services and not state.services:
            state.services = list(state.discovered_services)
            self.log(f"using {len(state.services)} services from CrawlerAgent analysis")

        # Strategy 2: CrawlerAgent discovered products
        if not state.products and not self.should_stop():
            if state.discovered_products:
                # Check confidence: nav-only products on platform sites are low-confidence
                nav_only = all(p.get("source") == "nav" for p in state.discovered_products)
                has_details = any(p.get("description") or p.get("image_urls") for p in state.discovered_products)

                if nav_only and not has_details and state.site_type == "platform":
                    self.log("low-confidence nav products on platform site — trying other strategies first")
                else:
                    state.products = list(state.discovered_products)
                    self._normalize_image_fields(state.products)
                    self.log(f"using {len(state.products)} products from CrawlerAgent analysis")

        # Strategy 3: HTML crawling from classified product pages
        if not state.products and not self.should_stop():
            product_pages = state.site_map.get("product", [])
            if product_pages:
                self.log(f"crawling {len(product_pages)} classified product pages")
                products = await self._scrape_from_pages(state, product_pages)
                if products:
                    state.products = products
                    self._normalize_image_fields(state.products)
                    self.log(f"extracted {len(products)} products from HTML")

        # Strategy 4: Extract from cached page content (last resort)
        # Skip for platform/saas sites with no discovered products — their cached
        # pages contain app download CTAs and promotional sections, not products.
        _skip_cached = (
            state.site_type in ("platform", "saas")
            and not state.discovered_products
        )
        if not state.products and not self.should_stop() and not _skip_cached:
            products = self._extract_from_cached(state)
            if products:
                state.products = products
                self._normalize_image_fields(state.products)
                self.log(f"extracted {len(products)} products from cached pages")

        # Final fallback: accept discovered products even if low-confidence
        if not state.products and state.discovered_products:
            state.products = list(state.discovered_products)
            self._normalize_image_fields(state.products)
            self.log(f"fallback: using {len(state.products)} discovered products")

        # Filter out bad product images
        if state.products:
            self._filter_product_images(state)
            self._filter_placeholder_images(state)

        # Build image map for downstream use
        state.product_image_map = [
            {"name": p.get("name", ""), "image_url": (p.get("image_urls") or [None])[0]}
            for p in state.products if p.get("image_urls")
        ]

        self.log(f"final: {len(state.products)} products, {len(state.services)} services")

    # ------------------------------------------------------------------
    async def _scrape_from_sitemap(self, state: ScrapeState) -> List[Dict]:
        """Scrape product detail pages from sitemap URLs (concurrent)."""
        from scraper_agents.extractors.product_parsing import scrape_product_detail

        urls = state.sitemap_urls[:CONCURRENCY["max_product_pages"]]

        def _scrape_all(urls_to_scrape: List[str]) -> List[Dict]:
            """Run in thread — uses ThreadPoolExecutor for true concurrency."""
            results = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as pool:
                futures = {
                    pool.submit(scrape_product_detail, u, DEFAULT_HEADERS): u
                    for u in urls_to_scrape
                }
                for f in concurrent.futures.as_completed(futures):
                    try:
                        product = f.result()
                        if product and product.get("name"):
                            results.append(product)
                    except Exception:
                        pass
            return results

        all_products = await asyncio.to_thread(_scrape_all, urls)
        return self._deduplicate(all_products)

    async def _scrape_from_listing_pages(self, state: ScrapeState) -> List[Dict]:
        """Crawl listing/category pages and extract product cards (parallel)."""
        from scraper_agents.extractors.product_parsing import extract_products_from_soup
        from scraper_agents.extractors.html_helpers import make_absolute_url
        from urllib.parse import urlparse

        all_products: List[Dict] = []
        seen_urls: set = set()
        max_pages = CONCURRENCY.get("max_listing_pages", 20)

        # Deduplicate listing URLs
        unique_urls = []
        for u in state.listing_urls[:max_pages]:
            if u not in seen_urls:
                seen_urls.add(u)
                unique_urls.append(u)

        if not unique_urls:
            return []

        # ── Fetch all listing pages in parallel ──────────────────────
        def _fetch(url: str):
            try:
                resp = requests.get(url, headers=DEFAULT_HEADERS,
                                    timeout=TIMEOUTS["product_detail_fetch"],
                                    allow_redirects=True)
                return url, resp
            except Exception:
                return url, None

        results = await asyncio.gather(
            *[asyncio.to_thread(_fetch, u) for u in unique_urls],
            return_exceptions=True,
        )

        # ── Process responses + discover sub-links ───────────────────
        sub_urls_to_fetch: List[str] = []
        pages_crawled = 0

        for result in results:
            if isinstance(result, Exception) or result is None:
                continue
            listing_url, resp = result
            if resp is None or resp.status_code != 200:
                continue
            pages_crawled += 1
            soup = BeautifulSoup(resp.text, "html.parser")
            parsed_listing = urlparse(listing_url)
            listing_base = f"{parsed_listing.scheme}://{parsed_listing.netloc}"

            products = extract_products_from_soup(soup, listing_base, DEFAULT_HEADERS)
            if products:
                all_products.extend(products)
                self.log(f"listing {listing_url[:60]}: {len(products)} products")

            # Collect sub-listing links for parallel fetch
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                abs_href = make_absolute_url(href, listing_base)
                if abs_href in seen_urls or not abs_href.startswith(listing_base):
                    continue
                if LOCALE_PATH_RE.search(urlparse(abs_href).path):
                    continue
                if not any(p in abs_href.lower() for p in ["/products/", "/shop/", "/collection/", "/collections/"]):
                    continue
                path_parts = [p for p in abs_href.replace(listing_base, "").strip("/").split("/") if p]
                last_seg = path_parts[-1] if path_parts else ""
                if len(last_seg) > 50:
                    continue
                if abs_href not in seen_urls:
                    seen_urls.add(abs_href)
                    sub_urls_to_fetch.append(abs_href)

        # ── Fetch sub-links in parallel ──────────────────────────────
        max_remaining = max_pages - pages_crawled
        if sub_urls_to_fetch and max_remaining > 0 and not self.should_stop():
            sub_results = await asyncio.gather(
                *[asyncio.to_thread(_fetch, u) for u in sub_urls_to_fetch[:max_remaining]],
                return_exceptions=True,
            )
            for result in sub_results:
                if isinstance(result, Exception) or result is None:
                    continue
                sub_url, resp = result
                if resp is None or resp.status_code != 200:
                    continue
                pages_crawled += 1
                sub_soup = BeautifulSoup(resp.text, "html.parser")
                parsed_sub = urlparse(sub_url)
                sub_base = f"{parsed_sub.scheme}://{parsed_sub.netloc}"
                sub_products = extract_products_from_soup(sub_soup, sub_base, DEFAULT_HEADERS)
                if sub_products:
                    all_products.extend(sub_products)
                    self.log(f"  sub {sub_url[:60]}: {len(sub_products)} products")

        return self._deduplicate(all_products)

    async def _scrape_from_pages(self, state: ScrapeState, pages) -> List[Dict]:
        """Extract products from classified product pages."""
        from scraper_agents.extractors.product_parsing import extract_products_from_soup

        all_products: List[Dict] = []
        for pi in pages[:10]:
            if self.should_stop():
                break
            html = state.page_cache.get(pi.url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            products = extract_products_from_soup(soup, state.base_url, DEFAULT_HEADERS)
            all_products.extend(products)

        return self._deduplicate(all_products)

    def _extract_from_cached(self, state: ScrapeState) -> List[Dict]:
        """Last resort: extract from any cached page that might have products."""
        from scraper_agents.extractors.product_parsing import extract_products_from_soup

        # Build set of URLs known to be non-product pages
        _SKIP_CATEGORIES = {"about", "blog", "contact", "careers", "gallery"}
        skip_urls: set = set()
        for cat in _SKIP_CATEGORIES:
            for pi in state.site_map.get(cat, []):
                skip_urls.add(pi.url)

        all_products: List[Dict] = []
        # Try homepage first
        if state.homepage_soup:
            products = extract_products_from_soup(
                state.homepage_soup, state.base_url, DEFAULT_HEADERS
            )
            all_products.extend(products)

        # Try cached pages, skipping known non-product pages
        for url, html in state.page_cache.items():
            if self.should_stop():
                break
            if url in skip_urls:
                self.log(f"skipping non-product page: {url[:80]}")
                continue
            try:
                soup = BeautifulSoup(html, "html.parser")
                products = extract_products_from_soup(soup, state.base_url, DEFAULT_HEADERS)
                if products:
                    self.log(f"found {len(products)} products in cached page: {url[:80]}")
                    all_products.extend(products)
            except Exception:
                pass

        return self._deduplicate(all_products)

    def _filter_product_images(self, state: ScrapeState) -> None:
        """Remove banner/carousel/logo images from product image lists."""
        logo_url = (state.logo_url or "").lower()

        for product in state.products:
            if not product.get("image_urls"):
                continue
            filtered = []
            for img_url in product["image_urls"]:
                url_lower = img_url.lower()

                # Reject if URL matches banner/carousel patterns
                if PRODUCT_IMAGE_REJECT_PATTERNS.search(url_lower):
                    continue

                # Reject if same as logo
                if logo_url and url_lower == logo_url:
                    continue

                filtered.append(img_url)

            product["image_urls"] = filtered if filtered else product["image_urls"][:1]

    @staticmethod
    def _filter_placeholder_images(state: ScrapeState) -> None:
        """Remove placeholder images shared by many products (generic og:image)."""
        if len(state.products) < 3:
            return
        # Count how many products share the same first image
        from collections import Counter
        img_counts: Counter = Counter()
        for p in state.products:
            urls = p.get("image_urls") or []
            if urls:
                img_counts[urls[0].lower()] += 1
        # If >50% of products share the same image, it's a placeholder
        threshold = max(3, len(state.products) * 0.5)
        placeholder_urls = {url for url, count in img_counts.items() if count >= threshold}
        if placeholder_urls:
            for p in state.products:
                urls = p.get("image_urls") or []
                filtered = [u for u in urls if u.lower() not in placeholder_urls]
                p["image_urls"] = filtered

    @staticmethod
    def _normalize_image_fields(products: List[Dict]) -> None:
        """Convert singular image_url to plural image_urls list."""
        for p in products:
            if "image_url" in p and not p.get("image_urls"):
                url = p.pop("image_url")
                p["image_urls"] = [url] if url else []
            elif "image_urls" not in p:
                p["image_urls"] = []

    @staticmethod
    def _deduplicate(products: List[Dict]) -> List[Dict]:
        """Deduplicate products by name + URL."""
        seen: set = set()
        unique: List[Dict] = []
        for p in products:
            key = (p.get("name", "").lower().strip(), p.get("url", ""))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique
