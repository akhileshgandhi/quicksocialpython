"""
Pure product-catalog extraction functions — sitemap parsing, product card
detection, detail-page scraping, and full catalog orchestration.

No AI calls, no state mutation. Configuration imported from scraper_agents.config.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from scraper_agents.config import (
    CONCURRENCY,
    LOCALE_PATH_RE,
    PRODUCT_IMAGE_REJECT_PATTERNS,
    PRODUCT_URL_PATTERNS,
    TAXONOMY_SEGMENTS,
    TIMEOUTS,
)
from scraper_agents.extractors.html_helpers import make_absolute_url

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal URL pattern lists (listing vs skip)
# ---------------------------------------------------------------------------

_LISTING_URL_PATTERNS = [
    '/products/', '/product/', '/shop/', '/store/', '/catalog/', '/catalogue/',
    '/collection/', '/collections/', '/range/', '/our-products/', '/all-products/',
    '/chocolate/', '/food/', '/drinks/', '/items/', '/menu/', '/offerings/',
]

_SKIP_URL_PATTERNS = [
    '/cart', '/checkout', '/account', '/login', '/register', '/search',
    '/blog/', '/news/', '/about', '/contact', '/faq', '/help', '/policy',
    '/terms', '/privacy', '/careers',
]

_CARD_KW = ['card', 'product', 'item', 'tile', 'grid', 'result']


def _extract_price(price_el) -> Optional[str]:
    """Extract price from a container, handling strikethrough/sale patterns.

    Handles:
    - WooCommerce: ``<del>₹9,499</del><ins>₹7,599</ins>``
    - Shopify: ``<span>Regular price</span><span>₹10</span>``
    """
    ins = price_el.find("ins")
    del_tag = price_el.find("del")
    if ins and del_tag:
        orig = del_tag.get_text(strip=True)[:30]
        sale = ins.get_text(strip=True)[:30]
        return f"~~{orig}~~ {sale}"
    if ins:
        return ins.get_text(strip=True)[:30]
    if del_tag:
        return del_tag.get_text(strip=True)[:30]

    # Shopify: look for <span class="price-item--*"> with actual currency
    for span in price_el.find_all("span"):
        text = span.get_text(strip=True)
        if text and re.search(r'[₹$€£¥]|Rs\.?|INR|USD', text):
            return text[:30]

    # Fallback: full text, strip common label prefixes
    raw = price_el.get_text(strip=True)[:60]
    if raw:
        # Strip "Regular price", "Sale price", "Price" prefixes
        raw = re.sub(r'^(Regular\s+price|Sale\s+price|Price)\s*', '', raw, flags=re.I).strip()
        # If there are two prices concatenated (e.g., "₹10₹10"), take the first
        prices = re.findall(r'[₹$€£¥][\s\d,.\-]+', raw)
        if prices:
            return prices[0].strip()[:30]
    return raw[:30] if raw else None


# ═══════════════════════════════════════════════════════════════════════════
# Sitemap parsing
# ═══════════════════════════════════════════════════════════════════════════

_SM_NS = 'http://www.sitemaps.org/schemas/sitemap/0.9'


def parse_sitemap(domain: str, headers: dict) -> List[str]:
    """
    Fetch ``robots.txt``, discover sitemap URLs, recursively parse XML
    sitemaps, and return all ``<loc>`` URLs found.

    Falls back to ``/sitemap.xml`` and ``/sitemap_index.xml`` if
    ``robots.txt`` does not declare a sitemap.
    """
    base_url = f"https://{domain}" if not domain.startswith("http") else domain
    base_url = base_url.rstrip("/")

    sitemap_urls_to_check: List[str] = []
    try:
        robots_resp = requests.get(
            f"{base_url}/robots.txt",
            headers=headers,
            timeout=TIMEOUTS["sitemap_fetch"],
        )
        if robots_resp.status_code == 200:
            sitemap_urls_to_check = re.findall(
                r'(?i)^Sitemap:\s*(\S+)', robots_resp.text, re.MULTILINE,
            )
    except Exception:
        pass

    if not sitemap_urls_to_check:
        sitemap_urls_to_check = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
        ]

    all_urls: List[str] = []
    for sm_url in sitemap_urls_to_check[:5]:
        found = _parse_sitemap_xml(sm_url, headers)
        all_urls.extend(found)
        if all_urls:
            break  # stop after first successful sitemap

    return all_urls


def _parse_sitemap_xml(
    sitemap_url: str,
    headers: dict,
    _depth: int = 0,
) -> List[str]:
    """Recursively parse a sitemap (handles sitemap index files one level deep)."""
    locs: List[str] = []
    if _depth > 1:
        return locs
    try:
        sr = requests.get(
            sitemap_url.strip(),
            headers=headers,
            timeout=TIMEOUTS["sitemap_fetch"] + 2,
        )
        if sr.status_code != 200:
            return locs
        root = ET.fromstring(sr.content)
        # Sitemap index -> recurse into child sitemaps (skip non-English locales)
        child_locs = root.findall(f'{{{_SM_NS}}}sitemap/{{{_SM_NS}}}loc')
        if child_locs:
            for child_el in child_locs[:15]:
                child_url = (child_el.text or '').strip()
                if child_url and not LOCALE_PATH_RE.search(urlparse(child_url).path):
                    locs.extend(_parse_sitemap_xml(child_url, headers, _depth + 1))
        else:
            for loc_el in root.findall(f'{{{_SM_NS}}}url/{{{_SM_NS}}}loc'):
                url = (loc_el.text or '').strip()
                if url and not LOCALE_PATH_RE.search(urlparse(url).path):
                    locs.append(url)
    except Exception:
        pass
    return locs


# ═══════════════════════════════════════════════════════════════════════════
# Product URL classification
# ═══════════════════════════════════════════════════════════════════════════

def is_listing_url(url: str) -> bool:
    """Return ``True`` if *url* looks like a product listing/category page."""
    url_lower = url.lower()
    if any(p in url_lower for p in _SKIP_URL_PATTERNS):
        return False
    return any(p in url_lower for p in _LISTING_URL_PATTERNS)


def is_product_detail_url(url: str) -> bool:
    """
    Return ``True`` if *url* looks like an individual product detail page.

    Rejects category/taxonomy pages (short slugs, known taxonomy segments)
    and non-product paths (cart, checkout, blog, etc.).
    """
    url_lower = url.lower()
    if any(p in url_lower for p in _SKIP_URL_PATTERNS):
        return False
    if not any(p in url_lower for p in _LISTING_URL_PATTERNS):
        return False

    # Parse just the path portion
    path = urlparse(url).path.strip('/')
    parts = [p for p in path.split('/') if p]

    # Need at least 2 segments: /products/product-slug/
    if len(parts) < 2:
        return False
    # Last segment must be long enough to be a product slug
    last_seg = parts[-1]
    if len(last_seg) <= 15:
        return False
    # Known taxonomy word in middle segments -> category page
    if any(seg in TAXONOMY_SEGMENTS for seg in parts[:-1]):
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════
# Product card extraction from HTML
# ═══════════════════════════════════════════════════════════════════════════

def extract_products_from_soup(
    soup: BeautifulSoup,
    base_url: str,
    headers: dict,
    category_hint: str = "",
    max_products: int = 300,
) -> List[Dict[str, Any]]:
    """
    Extract product cards from a single listing page.

    Strategy: find product links first (``<a>`` pointing to individual item
    pages), then walk UP the DOM to the smallest card-like ancestor that
    contains an image.

    Returns a list of ``{name, url, image_url, price, category, description}``.
    """
    found: List[Dict[str, Any]] = []
    seen_urls: set = set()
    seen_names: set = set()

    candidate_containers = []
    seen_container_ids: set = set()

    for a_tag in soup.find_all('a', href=True):
        href = a_tag['href'].strip()
        parts = [p for p in href.strip('/').split('/') if p]
        is_product_link = (
            len(parts) >= 2
            and any(p in href for p in _LISTING_URL_PATTERNS)
            and not any(p in href for p in _SKIP_URL_PATTERNS)
            and len(parts[-1]) > 4
        )
        if not is_product_link:
            continue

        # Walk UP from <a> to find smallest card ancestor with an image
        card = None
        node = a_tag.parent
        for _ in range(5):
            if node is None or node.name in ('body', 'html', '[document]'):
                break
            cls_str = ' '.join(node.get('class', [])).lower()
            has_card_kw = any(kw in cls_str for kw in _CARD_KW)
            has_img = bool(node.find('img'))
            if has_card_kw and has_img:
                card = node
                break
            if node == a_tag and (node.find('img') or node.find(['h2', 'h3', 'h4'])):
                card = node
                break
            node = node.parent

        if card is None:
            if a_tag.find('img') or a_tag.find(['h2', 'h3', 'h4', 'p']):
                card = a_tag

        if card is None:
            continue

        cid = id(card)
        if cid not in seen_container_ids:
            seen_container_ids.add(cid)
            candidate_containers.append(card)

    for container in candidate_containers[:max_products]:
        try:
            # Extract name: prefer heading tags, fallback to <p>/<span>
            name = ''
            for tag_name in ['h2', 'h3', 'h4', 'h5', 'strong']:
                el = container.find(tag_name)
                if el:
                    name = el.get_text(strip=True)
                    break
            if not name:
                for tag_name in ['p', 'span']:
                    for el in container.find_all(tag_name):
                        txt = el.get_text(strip=True)
                        if 3 <= len(txt) <= 100 and not txt.startswith('http'):
                            name = txt
                            break
                    if name:
                        break

            if not name or len(name) < 2:
                continue

            # Extract URL
            link_tag = container if container.name == 'a' else container.find('a', href=True)
            href = link_tag.get('href', '') if link_tag else ''
            product_url = make_absolute_url(href, base_url) if href else ''

            # Extract image
            img = container.find('img')
            img_url = ''
            if img:
                raw_src = _get_img_url(img)
                if raw_src:
                    img_url = make_absolute_url(raw_src, base_url)

            # Extract price (optional) — handles <del>/<ins> sale patterns
            price = None
            for price_sel in ['[class*="price"]', '[class*="cost"]', '[class*="amount"]']:
                price_el = container.select_one(price_sel)
                if price_el:
                    price = _extract_price(price_el)
                    if price:
                        break

            # Deduplicate
            name_key = name.lower().strip()[:80]
            if name_key in seen_names:
                continue
            if product_url and product_url in seen_urls:
                continue

            seen_names.add(name_key)
            if product_url:
                seen_urls.add(product_url)

            found.append({
                'name': name,
                'category': category_hint or '',
                'image_url': img_url,
                'url': product_url,
                'price': price,
                'description': '',
            })
        except Exception:
            continue

    return found


# ═══════════════════════════════════════════════════════════════════════════
# Single product detail page scraping
# ═══════════════════════════════════════════════════════════════════════════

def scrape_product_detail(url: str, headers: dict) -> Optional[Dict[str, Any]]:
    """
    Fetch a single product detail page and extract structured data.

    Returns ``{name, url, image_url, description, category, price}`` or
    ``None`` on failure.
    """
    try:
        r = requests.get(
            url,
            headers=headers,
            timeout=TIMEOUTS["product_detail_fetch"],
            allow_redirects=True,
        )
        if r.status_code != 200:
            return None

        detail_soup = BeautifulSoup(r.text, 'html.parser')

        # ── Name: og:title first (most reliable), then <title>, then <h1> ──
        name = ''
        # 1. og:title — almost always the exact product name
        og_title = detail_soup.find('meta', property='og:title')
        if og_title:
            raw_title = og_title.get('content', '').strip()
            # Strip site name suffix: "Product Name – Brand" or "Product Name | Brand"
            for sep in [' – ', ' - ', ' | ', ' · ']:
                if sep in raw_title:
                    raw_title = raw_title.split(sep)[0].strip()
            if raw_title and len(raw_title) >= 2:
                name = raw_title
        # 2. <title> tag fallback
        if not name:
            title_tag = detail_soup.find('title')
            if title_tag:
                raw_title = title_tag.get_text(strip=True)
                for sep in [' – ', ' - ', ' | ', ' · ']:
                    if sep in raw_title:
                        raw_title = raw_title.split(sep)[0].strip()
                if raw_title and len(raw_title) >= 2:
                    name = raw_title
        # 3. <h1> — but skip banners, alerts, announcements
        if not name:
            _BANNER_WORDS = {'beware', 'alert', 'warning', 'notice', 'attention',
                             'scam', 'fraud', 'important', 'announcement', 'cookie',
                             'subscribe', 'newsletter', 'sign up', 'log in'}
            for h1 in detail_soup.find_all('h1'):
                h1_text = h1.get_text(strip=True)
                if not h1_text or len(h1_text) < 2:
                    continue
                h1_lower = h1_text.lower()
                if any(bw in h1_lower for bw in _BANNER_WORDS):
                    continue
                name = h1_text
                break
        if not name or len(name) < 2:
            return None

        # Reject navigation/CTA headings
        _CTA_WORDS = {
            'explore', 'discover', 'shop', 'view', 'browse',
            'see all', 'find out', 'learn more',
        }
        name_lower = name.lower()
        if any(name_lower.startswith(cta) for cta in _CTA_WORDS):
            return None

        # ── Image: og:image first, then first large img in main ───────
        img_url = ''
        og_img = detail_soup.find('meta', property='og:image')
        if og_img:
            raw = og_img.get('content', '').strip()
            if raw and not raw.startswith('data:'):
                # Reject generic site-wide og:image placeholders
                raw_lower = raw.lower()
                _is_placeholder = any(kw in raw_lower for kw in [
                    'site-thumbnail', 'default-og', 'og-default',
                    'share-default', 'social-default', 'default-share',
                    'placeholder', 'fallback-image', 'og_image_default',
                ])
                if not _is_placeholder:
                    base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                    img_url = make_absolute_url(raw, base_url)
        if not img_url:
            base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
            # Try product-specific containers first, then generic main
            for container_sel in [
                '[class*="product-image"]', '[class*="product-gallery"]',
                '[class*="product-media"]', '[class*="product-hero"]',
                '[class*="pdp-image"]', '[class*="detail-image"]',
                'main', 'article', '[role="main"]',
            ]:
                container = detail_soup.select_one(container_sel)
                if container:
                    img = container.find('img')
                    if img:
                        raw_src = _get_img_url(img)
                        if raw_src:
                            img_url = make_absolute_url(raw_src, base_url)
                            break

        # ── Description: meta description or og:description ───────────
        desc = ''
        for meta_attrs in [{'name': 'description'}, {'property': 'og:description'}]:
            meta_el = detail_soup.find('meta', meta_attrs)
            if meta_el and meta_el.get('content'):
                desc = meta_el['content'].strip()[:300]
                break

        # ── Category: breadcrumb nav, then URL path ───────────────────
        category = ''
        breadcrumb = detail_soup.select_one(
            'nav[aria-label*="breadcrumb" i], [class*="breadcrumb"], [class*="crumb"]'
        )
        if breadcrumb:
            crumb_links = breadcrumb.find_all('a')
            if len(crumb_links) >= 2:
                category = crumb_links[-1].get_text(strip=True)
                if category.lower() == name.lower() and len(crumb_links) >= 3:
                    category = crumb_links[-2].get_text(strip=True)
        if not category:
            path = urlparse(url).path.strip('/')
            path_parts = [p for p in path.split('/') if p]
            if len(path_parts) >= 3:
                category = path_parts[-2].replace('-', ' ').title()

        # ── Price (optional) — handles <del>/<ins> sale patterns ────
        price = None
        for price_sel in ['[class*="price"]', '[class*="cost"]', '[class*="amount"]']:
            price_el = detail_soup.select_one(price_sel)
            if price_el:
                price = _extract_price(price_el)
                if price:
                    break

        return {
            'name': name,
            'category': category,
            'image_url': img_url,
            'url': url,
            'price': price,
            'description': desc,
        }
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Full product catalog scraper
# ═══════════════════════════════════════════════════════════════════════════

def scrape_product_catalog(
    domain: str,
    base_url: str,
    nav_links: List[Dict[str, Any]],
    site_map_products: List[str],
    sitemap_urls: List[str],
    headers: dict,
    max_products: int = 300,
) -> List[Dict[str, Any]]:
    """
    Full product-catalog scraper.

    Strategy order:
    1. **Sitemap**: if *sitemap_urls* (pre-parsed ``<loc>`` URLs) are
       provided, filter for product-detail URLs and scrape them concurrently.
    2. **HTML crawling fallback**: discover listing pages from *nav_links*
       (or common paths), extract product cards, and follow sub-listing /
       pagination links.

    Returns up to *max_products* structured product dicts.
    """
    import concurrent.futures as _cf

    max_listing_pages = CONCURRENCY["max_listing_pages"]
    max_detail_workers = CONCURRENCY["product_detail_workers"]

    products: List[Dict[str, Any]] = []
    seen_urls: set = set()
    seen_names: set = set()

    # ── Step 0: Sitemap-based discovery ───────────────────────────────
    # Use pre-supplied sitemap_urls if available, else parse from scratch
    all_sitemap_urls = list(sitemap_urls) if sitemap_urls else []
    if not all_sitemap_urls and site_map_products:
        all_sitemap_urls = list(site_map_products)

    if not all_sitemap_urls:
        try:
            all_sitemap_urls = parse_sitemap(domain, headers)
        except Exception as e:
            logger.debug(f"   [CATALOG] Sitemap discovery failed: {e}")

    sitemap_product_urls = [u for u in all_sitemap_urls if is_product_detail_url(u)]
    sitemap_product_urls = list(dict.fromkeys(sitemap_product_urls))  # deduplicate
    logger.info(
        f"   [CATALOG] Sitemap: {len(all_sitemap_urls)} total URLs, "
        f"{len(sitemap_product_urls)} product URLs"
    )

    if sitemap_product_urls:
        logger.info(
            f"   [CATALOG] Scraping {min(len(sitemap_product_urls), max_products)}"
            f" product detail pages from sitemap..."
        )
        with _cf.ThreadPoolExecutor(max_workers=max_detail_workers) as pool:
            futures = {
                pool.submit(scrape_product_detail, url, headers): url
                for url in sitemap_product_urls[:max_products]
            }
            for future in _cf.as_completed(futures):
                result = future.result()
                if result and result.get('name'):
                    name_key = result['name'].lower().strip()[:80]
                    if name_key not in seen_names:
                        seen_names.add(name_key)
                        if result.get('url'):
                            seen_urls.add(result['url'])
                        products.append(result)
        products.sort(key=lambda p: p.get('url', ''))
        logger.info(f"   [CATALOG] Sitemap scrape complete: {len(products)} products")
        return products[:max_products]

    # ── HTML crawling fallback ────────────────────────────────────────

    def _is_listing_url(url: str) -> bool:
        url_lower = url.lower()
        if any(p in url_lower for p in _SKIP_URL_PATTERNS):
            return False
        return any(p in url_lower for p in _LISTING_URL_PATTERNS)

    # Discover listing pages from nav links
    listing_pages: List[tuple] = []
    seen_listing_urls: set = set()

    for nav_link in nav_links:
        url = nav_link.get('url', '')
        text = nav_link.get('text', '')
        if url and _is_listing_url(url):
            abs_url = make_absolute_url(url, base_url)
            if abs_url not in seen_listing_urls:
                listing_pages.append((abs_url, text))
                seen_listing_urls.add(abs_url)

    # Fallback: try common product paths
    if not listing_pages:
        for path in ['/products/', '/shop/', '/store/', '/collection/', '/range/']:
            candidate = base_url.rstrip('/') + path
            if candidate not in seen_listing_urls:
                listing_pages.append((candidate, ''))
                seen_listing_urls.add(candidate)

    if not listing_pages:
        return []

    logger.info(f"   [CATALOG] Found {len(listing_pages)} product listing page(s) to crawl")

    pages_crawled = 0
    for listing_url, category_hint in listing_pages[:max_listing_pages]:
        if len(products) >= max_products:
            break
        try:
            resp = requests.get(
                listing_url,
                headers=headers,
                timeout=TIMEOUTS["product_detail_fetch"] + 2,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            page_soup = BeautifulSoup(resp.text, 'html.parser')
            pages_crawled += 1

            page_products = extract_products_from_soup(
                page_soup, base_url, headers, category_hint,
            )
            products.extend(page_products)
            logger.info(
                f"   [CATALOG] {listing_url}: {len(page_products)} products"
                f" (total: {len(products)})"
            )

            # ── Follow sub-listing links on this page ─────────────────
            sub_links: set = set()
            for a_tag in page_soup.find_all('a', href=True):
                href = a_tag['href'].strip()
                abs_href = make_absolute_url(href, base_url)
                if abs_href in seen_listing_urls or not abs_href.startswith(base_url):
                    continue
                if not _is_listing_url(abs_href):
                    continue
                path_parts = [
                    p for p in abs_href.replace(base_url, '').strip('/').split('/') if p
                ]
                last_seg = path_parts[-1] if path_parts else ''
                if len(last_seg) > 50 or (
                    any(c.isdigit() for c in last_seg) and len(last_seg) > 25
                ):
                    continue
                sub_links.add(abs_href)

            for sub_url in list(sub_links)[:30]:
                if len(products) >= max_products or pages_crawled >= max_listing_pages:
                    break
                if sub_url in seen_listing_urls:
                    continue
                seen_listing_urls.add(sub_url)
                try:
                    sub_resp = requests.get(
                        sub_url,
                        headers=headers,
                        timeout=TIMEOUTS["product_detail_fetch"] + 2,
                        allow_redirects=True,
                    )
                    if sub_resp.status_code != 200:
                        continue
                    sub_soup = BeautifulSoup(sub_resp.text, 'html.parser')
                    pages_crawled += 1
                    sub_category = sub_url.rstrip('/').rsplit('/', 1)[-1].replace('-', ' ').title()
                    sub_products = extract_products_from_soup(
                        sub_soup, base_url, headers, sub_category,
                    )
                    products.extend(sub_products)
                    logger.info(
                        f"   [CATALOG]   sub {sub_url}: {len(sub_products)} products"
                        f" (total: {len(products)})"
                    )

                    # Follow pagination on sub-listing pages
                    next_url = _find_next_page_url(sub_soup, sub_url, base_url)
                    if next_url and next_url not in seen_listing_urls:
                        seen_listing_urls.add(next_url)
                        try:
                            pg_resp = requests.get(
                                next_url,
                                headers=headers,
                                timeout=TIMEOUTS["product_detail_fetch"] + 2,
                            )
                            if pg_resp.status_code == 200:
                                pages_crawled += 1
                                pg_soup = BeautifulSoup(pg_resp.text, 'html.parser')
                                pg_products = extract_products_from_soup(
                                    pg_soup, base_url, headers, sub_category,
                                )
                                products.extend(pg_products)
                                logger.info(
                                    f"   [CATALOG]   paginated {next_url}:"
                                    f" {len(pg_products)} products"
                                )
                        except Exception:
                            pass
                except Exception:
                    continue

        except Exception as e:
            logger.debug(f"   [CATALOG] Failed to scrape {listing_url}: {e}")
            continue

    # Deduplicate final list by name
    final: List[Dict[str, Any]] = []
    final_names: set = set()
    for p in products:
        key = p['name'].lower().strip()[:80]
        if key not in final_names:
            final_names.add(key)
            final.append(p)

    logger.info(
        f"   [CATALOG] Complete: {len(final)} unique products"
        f" across {pages_crawled} pages"
    )
    return final[:max_products]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_img_url(tag) -> str:
    """Extract image URL from an ``<img>`` tag, trying lazy-load variants."""
    for attr in ['src', 'data-src', 'data-lazy-src', 'data-original', 'data-srcset']:
        val = tag.get(attr, '')
        if val and not val.startswith('data:') and 'placeholder' not in val.lower():
            if ',' in val and ' ' in val:
                val = val.split(',')[0].split()[0]
            return val.strip()
    srcset = tag.get('srcset', '')
    if srcset:
        first = srcset.split(',')[0].split()[0]
        if first and not first.startswith('data:'):
            return first.strip()
    return ''


def _find_next_page_url(
    soup: BeautifulSoup,
    current_url: str,
    base_url: str,
) -> Optional[str]:
    """Find a "next page" pagination link on the current listing page."""
    for a_tag in soup.find_all('a', href=True):
        txt = a_tag.get_text(strip=True).lower()
        href_lower = a_tag['href'].lower()
        if any(
            kw in txt or kw in href_lower
            for kw in ['next', 'next page', 'page=2', 'page/2', 'offset=']
        ):
            candidate = make_absolute_url(a_tag['href'], base_url)
            if candidate != current_url and candidate.startswith(base_url):
                return candidate
    return None