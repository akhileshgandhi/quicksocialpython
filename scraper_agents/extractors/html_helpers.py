"""
Pure HTML / URL helper functions used across multiple agents.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

def make_absolute_url(src: str, base_url: str) -> str:
    """Resolve *src* against *base_url* into an absolute URL."""
    if src.startswith("//"):
        return f"https:{src}"
    elif src.startswith("/"):
        return urljoin(base_url, src)
    elif not src.startswith("http"):
        return urljoin(base_url, src)
    return src


def domain_from_url(url: str) -> str:
    """Extract the bare domain from a URL (e.g. 'www.dabur.com' → 'dabur.com')."""
    netloc = urlparse(url).netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def is_home_like_href(href: str, base_url: str) -> bool:
    """Return True if *href* points to the homepage (/, /en, base domain)."""
    if not href:
        return False
    href = href.strip().rstrip("/")
    if href in ("", "/", "#"):
        return True
    parsed_base = urlparse(base_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    if href.rstrip("/") == base_origin.rstrip("/"):
        return True
    # /en, /en-us, /in, /en-in.html etc.
    parsed_href = urlparse(href)
    href_path = parsed_href.path.rstrip("/")
    if re.match(r'^/[a-z]{2}(-[a-z]{2})?(\.html?)?$', href_path, re.IGNORECASE):
        return True
    # Full URL with locale path: https://example.com/en-in.html
    if href.startswith(base_origin):
        rel_path = href[len(base_origin):].rstrip("/")
        if re.match(r'^/[a-z]{2}(-[a-z]{2})?(\.html?)?$', rel_path, re.IGNORECASE):
            return True
    return False


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

def extract_og_data(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract Open Graph meta tags into a dict."""
    og: Dict[str, str] = {}
    for meta in soup.find_all("meta", attrs={"property": True}):
        prop = meta.get("property", "")
        if prop.startswith("og:"):
            og[prop[3:]] = meta.get("content", "")
    return og


def extract_title(soup: BeautifulSoup) -> str:
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else ""


def extract_meta(soup: BeautifulSoup, name: str) -> str:
    tag = soup.find("meta", attrs={"name": name})
    return (tag.get("content", "") if tag else "").strip()


def extract_headings(soup: BeautifulSoup, levels: str = "h1,h2,h3") -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for tag in soup.select(levels):
        text = tag.get_text(strip=True)
        if text:
            results.append({"level": tag.name, "text": text[:300]})
    return results


def extract_paragraphs(soup: BeautifulSoup, limit: int = 30) -> List[str]:
    paras: List[str] = []
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 30:
            paras.append(text[:500])
            if len(paras) >= limit:
                break
    return paras


# ---------------------------------------------------------------------------
# Navigation link extraction
# ---------------------------------------------------------------------------

def extract_nav_links(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    """Extract links from <nav> and <header> elements."""
    links: List[Dict[str, str]] = []
    seen_hrefs: set = set()
    for container in soup.select("nav, header"):
        for a_tag in container.find_all("a", href=True):
            href = a_tag["href"].strip()
            if href.startswith("#") or href.startswith("javascript:"):
                continue
            abs_url = make_absolute_url(href, base_url)
            if abs_url in seen_hrefs:
                continue
            seen_hrefs.add(abs_url)
            text = a_tag.get_text(strip=True)[:100]
            links.append({"url": abs_url, "text": text, "href": href})
    return links


# ---------------------------------------------------------------------------
# Structured data (JSON-LD)
# ---------------------------------------------------------------------------

def extract_jsonld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Parse all <script type="application/ld+json"> tags."""
    import json
    results: List[Dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.get_text())
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict):
                results.append(data)
        except (json.JSONDecodeError, ValueError):
            pass
    return results


def extract_jsonld_logo(structured_data: List[Dict[str, Any]]) -> Optional[str]:
    """Return the Organization / WebSite logo URL from JSON-LD if present."""
    for item in structured_data:
        if item.get("@type") in ("Organization", "WebSite", "Corporation"):
            logo = item.get("logo")
            if isinstance(logo, str):
                return logo
            if isinstance(logo, dict):
                return logo.get("url") or logo.get("contentUrl")
        # Handle @graph arrays
        graph = item.get("@graph", [])
        if isinstance(graph, list):
            for node in graph:
                if isinstance(node, dict) and node.get("@type") in ("Organization", "WebSite", "Corporation"):
                    logo = node.get("logo")
                    if isinstance(logo, str):
                        return logo
                    if isinstance(logo, dict):
                        return logo.get("url") or logo.get("contentUrl")
    return None


def extract_jsonld_products(structured_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract products with prices from JSON-LD Product/Offer/Menu schemas.

    This parses the website's own structured data — the most factual source
    of product information (used by Shopify, WooCommerce, Magento, brand sites
    for SEO).
    """
    products: List[Dict[str, Any]] = []

    def _parse_product(node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract a product dict from a schema.org Product node."""
        name = node.get("name", "").strip()
        if not name:
            return None

        # Price from offers
        price = None
        offers = node.get("offers")
        if isinstance(offers, dict):
            price = _extract_price_from_offer(offers)
        elif isinstance(offers, list):
            # Multiple offers — take the first with a price
            for offer in offers:
                if isinstance(offer, dict):
                    price = _extract_price_from_offer(offer)
                    if price:
                        break

        # Image(s) — filter out social-media icons & generic sharing images
        _IMG_REJECT_KW = {"instagram", "facebook", "twitter", "linkedin",
                          "youtube", "tiktok", "social", "icon", "logo",
                          "badge", "banner", "placeholder", "default"}

        def _ok_img(url: str) -> bool:
            fn = url.rsplit("/", 1)[-1].lower() if "/" in url else url.lower()
            return not any(kw in fn for kw in _IMG_REJECT_KW)

        image_urls: List[str] = []
        img = node.get("image")
        if isinstance(img, str) and img and _ok_img(img):
            image_urls.append(img)
        elif isinstance(img, list):
            for i in img:
                if isinstance(i, str) and i and _ok_img(i):
                    image_urls.append(i)
                elif isinstance(i, dict):
                    url = i.get("url") or i.get("contentUrl")
                    if url and _ok_img(url):
                        image_urls.append(url)
        elif isinstance(img, dict):
            url = img.get("url") or img.get("contentUrl")
            if url and _ok_img(url):
                image_urls.append(url)

        return {
            "name": name,
            "description": (node.get("description") or "")[:200],
            "price": price,
            "image_urls": image_urls[:3],
            "url": node.get("url", ""),
            "category": node.get("category", "") if isinstance(node.get("category"), str) else "",
        }

    def _extract_price_from_offer(offer: Dict[str, Any]) -> Optional[str]:
        """Pull price string from an Offer or AggregateOffer node."""
        otype = offer.get("@type", "")

        # AggregateOffer — use lowPrice or highPrice
        if otype == "AggregateOffer":
            low = offer.get("lowPrice")
            high = offer.get("highPrice")
            currency = offer.get("priceCurrency", "")
            if low and high and str(low) != str(high):
                return f"{currency} {low} - {high}".strip()
            elif low:
                return f"{currency} {low}".strip()
            elif high:
                return f"{currency} {high}".strip()
            price_range = offer.get("priceRange")
            if price_range:
                return str(price_range)

        # Regular Offer
        price = offer.get("price")
        if price is not None and str(price).strip():
            currency = offer.get("priceCurrency", "")
            return f"{currency} {price}".strip()

        price_spec = offer.get("priceSpecification")
        if isinstance(price_spec, dict):
            p = price_spec.get("price")
            if p is not None:
                currency = price_spec.get("priceCurrency", "")
                return f"{currency} {p}".strip()

        return None

    def _process_node(node: Dict[str, Any]) -> None:
        """Process a single JSON-LD node (or recurse into @graph / ItemList)."""
        if not isinstance(node, dict):
            return
        ntype = node.get("@type", "")
        # Normalize type — can be a list like ["Product", "IndividualProduct"]
        if isinstance(ntype, list):
            ntype = " ".join(ntype)

        # Product
        if "Product" in ntype:
            prod = _parse_product(node)
            if prod:
                products.append(prod)

        # MenuItem (restaurants)
        elif ntype in ("MenuItem", "MenuSection"):
            name = node.get("name", "").strip()
            if name:
                price = None
                offers = node.get("offers")
                if isinstance(offers, dict):
                    price = _extract_price_from_offer(offers)
                elif isinstance(offers, list):
                    for o in offers:
                        if isinstance(o, dict):
                            price = _extract_price_from_offer(o)
                            if price:
                                break
                products.append({
                    "name": name,
                    "description": (node.get("description") or "")[:200],
                    "price": price,
                    "image_urls": [],
                    "url": node.get("url", ""),
                    "category": "Menu",
                })
            # MenuSection may have sub-items
            for item in node.get("hasMenuItem", []):
                _process_node(item)
            for section in node.get("hasMenuSection", []):
                _process_node(section)

        # Menu (container)
        elif ntype == "Menu":
            for section in node.get("hasMenuSection", []):
                _process_node(section)
            for item in node.get("hasMenuItem", []):
                _process_node(item)

        # ItemList (product collections — common on e-commerce category pages)
        elif ntype == "ItemList":
            for elem in node.get("itemListElement", []):
                if not isinstance(elem, dict):
                    continue
                inner = elem.get("item")
                if isinstance(inner, dict):
                    _process_node(inner)
                elif elem.get("name"):
                    # ListItem with name/url/image directly on it (Mamaearth style)
                    img = elem.get("image", "")
                    img_list = [img] if isinstance(img, str) and img else []
                    products.append({
                        "name": elem["name"].strip(),
                        "description": (elem.get("description") or "")[:200],
                        "price": None,
                        "image_urls": img_list[:3],
                        "url": elem.get("url", ""),
                        "category": "",
                    })
                else:
                    _process_node(elem)

        # @graph array
        graph = node.get("@graph")
        if isinstance(graph, list):
            for child in graph:
                if isinstance(child, dict):
                    _process_node(child)

    # Process all top-level JSON-LD items
    for item in structured_data:
        _process_node(item)

    return products[:50]  # cap at 50 to prevent bloat


# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------

def extract_favicon(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Best favicon URL from <link> tags."""
    candidates: List[tuple] = []  # (priority, url)
    for link in soup.find_all("link", rel=True):
        rels = " ".join(link["rel"]).lower()
        href = link.get("href", "").strip()
        if not href:
            continue
        if "apple-touch-icon" in rels:
            candidates.append((1, make_absolute_url(href, base_url)))
        elif "icon" in rels:
            sizes = link.get("sizes", "")
            # prefer larger icons
            try:
                w = int(sizes.split("x")[0])
                priority = 2 if w >= 64 else 4
            except (ValueError, IndexError):
                priority = 3
            candidates.append((priority, make_absolute_url(href, base_url)))
    if not candidates:
        # fallback: /favicon.ico
        parsed = urlparse(base_url)
        candidates.append((5, f"{parsed.scheme}://{parsed.netloc}/favicon.ico"))
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1] if candidates else None


# ---------------------------------------------------------------------------
# Image candidate extraction
# ---------------------------------------------------------------------------

def get_img_src(img_tag: Tag) -> Optional[str]:
    """Get the best image src from an <img> tag (handles lazy-load attrs)."""
    for attr in ("src", "data-src", "data-lazy-src", "data-original", "srcset"):
        val = img_tag.get(attr, "").strip()
        if val and not val.startswith("data:image/svg+xml"):
            if attr == "srcset":
                # take first URL from srcset
                val = val.split(",")[0].split()[0]
            return val
    return None


def extract_all_images(soup: BeautifulSoup, base_url: str, limit: int = 200) -> List[Dict[str, Any]]:
    """Extract all meaningful <img> tags from *soup* with logo-scoring metadata."""
    images: List[Dict[str, Any]] = []
    seen: set = set()

    # Pre-compute header/nav containers for in_header detection
    _header_tags: set = set()
    for container in soup.select("header, nav, [role='banner']"):
        _header_tags.add(id(container))
        for child in container.descendants:
            if hasattr(child, 'name'):
                _header_tags.add(id(child))

    # Pre-compute "Trusted by / Clients / Partners" sections — images inside
    # these are OTHER companies' logos, not the site's own logo.
    _TRUSTED_KW = {"trusted", "client", "partner", "as seen", "featured in",
                   "our clients", "our partners", "brands we", "companies we",
                   "they trust", "work with", "associated"}
    _client_tags: set = set()
    for section in soup.find_all(["section", "div", "aside"]):
        # Check headings and text content near the section start
        heading = section.find(["h1", "h2", "h3", "h4", "h5", "h6", "p", "span"])
        if heading:
            heading_text = heading.get_text(strip=True).lower()
            if any(kw in heading_text for kw in _TRUSTED_KW):
                _client_tags.add(id(section))
                for child in section.descendants:
                    if hasattr(child, 'name'):
                        _client_tags.add(id(child))

    # Priority CSS selectors for logo detection
    _LOGO_SELECTORS = {
        ".logo img", "#logo img", ".site-logo img", ".brand-logo img",
        ".navbar-brand img", ".nav-logo img", ".header-logo img",
        "[class*='logo'] img", "[id*='logo'] img",
    }
    _priority_srcs: set = set()
    for sel in _LOGO_SELECTORS:
        try:
            for el in soup.select(sel):
                s = get_img_src(el)
                if s:
                    _priority_srcs.add(make_absolute_url(s, base_url))
        except Exception:
            pass

    first_in_nav_found = False
    for img in soup.find_all("img"):
        src = get_img_src(img)
        if not src:
            continue
        abs_url = make_absolute_url(src, base_url)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        alt = img.get("alt", "").strip()
        cls = " ".join(img.get("class", []))
        w_raw = img.get("width", "")
        h_raw = img.get("height", "")
        width = int(w_raw) if str(w_raw).isdigit() else None
        height = int(h_raw) if str(h_raw).isdigit() else None

        # Detect if in header/nav
        in_header = id(img) in _header_tags

        # Find ancestor <a> href
        ancestor_href = None
        node = img.parent
        for _ in range(6):
            if not node or getattr(node, 'name', None) in (None, '[document]', 'body', 'html'):
                break
            if node.name == 'a' and node.get('href'):
                href = node['href'].strip()
                if href and not href.startswith('#') and not href.startswith('javascript:'):
                    ancestor_href = make_absolute_url(href, base_url)
                break
            node = node.parent

        is_home = is_home_like_href(ancestor_href, base_url) if ancestor_href else False
        is_first = False
        if in_header and not first_in_nav_found:
            first_in_nav_found = True
            is_first = True

        in_client_section = id(img) in _client_tags

        images.append({
            "src": abs_url,
            "alt": alt,
            "class": cls,
            "width": width,
            "height": height,
            "in_header": in_header,
            "is_home_link": is_home,
            "is_first_in_nav": is_first,
            "priority_selector": abs_url in _priority_srcs,
            "ancestor_href": ancestor_href,
            "in_client_section": in_client_section,
        })
        if len(images) >= limit:
            break
    return images


# ---------------------------------------------------------------------------
# Country inference from TLD
# ---------------------------------------------------------------------------

_TLD_COUNTRY = {
    '.in': 'IN', '.co.in': 'IN', '.uk': 'GB', '.co.uk': 'GB',
    '.au': 'AU', '.com.au': 'AU', '.ca': 'CA', '.de': 'DE',
    '.fr': 'FR', '.jp': 'JP', '.co.jp': 'JP', '.br': 'BR',
    '.com.br': 'BR', '.it': 'IT', '.es': 'ES', '.nl': 'NL',
    '.sg': 'SG', '.com.sg': 'SG', '.ae': 'AE', '.sa': 'SA',
    '.za': 'ZA', '.co.za': 'ZA', '.nz': 'NZ', '.co.nz': 'NZ',
    '.kr': 'KR', '.co.kr': 'KR', '.mx': 'MX', '.com.mx': 'MX',
    '.cn': 'CN', '.com.cn': 'CN', '.ru': 'RU', '.se': 'SE',
    '.no': 'NO', '.fi': 'FI', '.dk': 'DK', '.pl': 'PL',
}

def infer_country_from_tld(url: str) -> Optional[str]:
    """Return ISO country code inferred from the URL's TLD, or None."""
    domain = urlparse(url).netloc.lower()
    # check longer TLDs first (.co.in before .in)
    for tld in sorted(_TLD_COUNTRY, key=len, reverse=True):
        if domain.endswith(tld):
            return _TLD_COUNTRY[tld]
    return None


# ---------------------------------------------------------------------------
# Navigation dropdown → product list
# ---------------------------------------------------------------------------

_PRODUCT_TRIGGERS = re.compile(
    r'^(products?|solutions?|platform|our\s+products?|services?)$',
    re.IGNORECASE,
)

_SKIP_LINK_TEXT = re.compile(
    r'^(learn more|see all|view all|overview|sign up|free trial|'
    r'get started|contact|pricing|compare|log\s*in|register|'
    r'explore all|all products|download|watch demo|request demo|'
    r'see plans|see pricing|read more|try for free|buy now)$',
    re.IGNORECASE,
)

_SKIP_URL_SEGMENTS = re.compile(
    r'/(blog|about|contact|pricing|support|help|careers|press|'
    r'newsroom|legal|privacy|terms|login|signup|register|docs'
    r'|documentation|community|partners|events|webinars?)/',
    re.IGNORECASE,
)

# External app-store domains — nav links pointing here are NOT products
_EXTERNAL_APP_DOMAINS = {
    "play.google.com", "apps.apple.com", "itunes.apple.com",
    "market.android.com", "snapcraft.io", "galaxy.store",
    "chrome.google.com", "addons.mozilla.org",
}

_APP_STORE_URL_RE = re.compile(
    r'(play\.google\.com|apps\.apple\.com|itunes\.apple\.com|'
    r'/store/apps/|/app/id\d+)',
    re.IGNORECASE,
)

# Nav items that are actually app-store / generic terms, not products
_APP_STORE_TERMS = {
    "play pass", "play points", "play games", "app store", "google play",
    "apple store", "gift cards", "download app", "get the app",
    "android app", "iphone app", "ios app", "mobile app",
}

# Colon-prefixed subsection header pattern: "BrandName: Description of section"
_SUBSECTION_HEADER_RE = re.compile(r'^[A-Z][a-zA-Z]+\s*:')

# URL path segments that indicate a product listing page (not a specific product)
_PRODUCT_URL_RE = re.compile(r'/products?/([^/?#]+)', re.IGNORECASE)
_SOLUTIONS_URL_RE = re.compile(r'/solutions?/([^/?#]+)', re.IGNORECASE)


def _extract_name_from_link(a_tag: Tag) -> str:
    """Extract the product name from a nav link <a> tag.

    Strategy:
    1. Look for a visually-hidden span (accessibility label) — cleanest name.
    2. Look for a heading-like child element and take its first direct text node.
    3. Fall back to the first text child (before description text is appended).
    """
    # Strategy 1: visually-hidden span
    vh = a_tag.find(class_=lambda c: c and "visually-hidden" in " ".join(c))
    if vh:
        name = vh.get_text(strip=True)
        if name:
            return name

    # Strategy 2: heading child — take direct text (exclude nested spans)
    heading = a_tag.find(
        class_=lambda c: c and any("heading" in cls for cls in (c if isinstance(c, list) else [c]))
    )
    if heading:
        # Collect only direct text nodes (NavigableString), skip child tags
        direct = "".join(
            str(child).strip() for child in heading.children
            if not hasattr(child, "name") or child.name is None
        ).strip()
        if direct:
            return direct

    # Strategy 3: first navigable string in the <a> tag
    for child in a_tag.children:
        if not hasattr(child, "name") or child.name is None:
            text = str(child).strip()
            if text:
                return text
        elif child.name in ("span", "strong", "b"):
            text = child.get_text(strip=True)
            if text and len(text) < 40:
                return text

    return a_tag.get_text(strip=True)[:40]


def _name_from_url_slug(url: str) -> Optional[str]:
    """Derive a product name from a URL slug like /products/virtual-meetings/."""
    m = _PRODUCT_URL_RE.search(url) or _SOLUTIONS_URL_RE.search(url)
    if not m:
        return None
    slug = m.group(1)
    # Skip generic category slugs
    if slug.lower() in ("all", "overview", "features", "solutions", "index"):
        return None
    return slug.replace("-", " ").replace("_", " ").title()


def extract_nav_products(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    """Extract product names from navigation dropdown menus.

    Uses two strategies:
    1. Trigger-word approach: find a "Products"/"Solutions" link, collect its
       dropdown children.
    2. URL-based approach: find all nav/header links whose URL contains
       ``/products/<slug>`` or ``/solutions/<slug>`` and extract the name
       from the link text or URL slug.

    Returns a deduplicated list of ``{"name": ..., "url": ...}`` (max 30).
    """
    products: List[Dict[str, str]] = []
    seen_names: set = set()
    seen_urls: set = set()
    site_domain = domain_from_url(base_url)

    def _is_external(url: str) -> bool:
        """True if url points to a different domain (app stores, etc.)."""
        link_domain = domain_from_url(url)
        if not link_domain:
            return False
        # Same domain or subdomain → internal
        if link_domain == site_domain or link_domain.endswith("." + site_domain):
            return False
        return True

    def _add(name: str, url: str) -> bool:
        name = name.strip()
        if not name or len(name) > 60:
            return False
        if _SKIP_LINK_TEXT.match(name):
            return False
        # Reject external domain links (app stores, etc.)
        if _is_external(url):
            return False
        # Reject app-store URL patterns
        if _APP_STORE_URL_RE.search(url):
            return False
        # Reject known app-store terms
        if name.lower().strip() in _APP_STORE_TERMS:
            return False
        # Reject long colon-prefixed subsection headers ("District: Movies Events Dining")
        if _SUBSECTION_HEADER_RE.match(name) and len(name) > 25:
            return False
        key = name.lower()
        if key in seen_names or url in seen_urls:
            return False
        seen_names.add(key)
        seen_urls.add(url)
        products.append({"name": name, "url": url})
        return len(products) >= 30

    # ── Strategy 1: Trigger-word dropdown ───────────────────────────────
    for container in soup.select("nav, header"):
        for trigger in container.find_all("a", href=True):
            trigger_text = trigger.get_text(strip=True)
            if not _PRODUCT_TRIGGERS.match(trigger_text):
                continue
            parent = trigger.parent
            for _ in range(3):
                if parent is None:
                    break
                if parent.name in ("li", "div") and parent != trigger:
                    break
                parent = parent.parent
            if parent is None:
                continue
            for a_tag in parent.find_all("a", href=True):
                if a_tag is trigger:
                    continue
                text = _extract_name_from_link(a_tag)
                href = a_tag["href"].strip()
                abs_url = make_absolute_url(href, base_url)
                if _SKIP_URL_SEGMENTS.search(abs_url):
                    continue
                if _add(text, abs_url):
                    return products

    # ── Strategy 2: URL-based — collect /products/<slug> links from nav ─
    if not products:
        for container in soup.select("nav, header"):
            for a_tag in container.find_all("a", href=True):
                href = a_tag["href"].strip()
                abs_url = make_absolute_url(href, base_url)
                if not (_PRODUCT_URL_RE.search(abs_url) or _SOLUTIONS_URL_RE.search(abs_url)):
                    continue
                if _SKIP_URL_SEGMENTS.search(abs_url):
                    continue
                # Extract clean product name
                name = _extract_name_from_link(a_tag)
                if not name or _SKIP_LINK_TEXT.match(name):
                    name = _name_from_url_slug(abs_url) or ""
                if _add(name, abs_url):
                    return products

    return products


def nav_products_are_taxonomy(nav_products: List[Dict[str, str]]) -> bool:
    """Return True if nav products look like category/brand listings.

    Checks whether ≥30% of the nav product URLs contain taxonomy path
    segments (brands, collections, categories, flavour, etc.).  If so,
    these are category pages — not individual products — and catalog
    crawling should NOT be skipped.
    """
    if not nav_products:
        return False
    from scraper_agents.config import TAXONOMY_SEGMENTS
    taxonomy_count = 0
    for p in nav_products:
        url_path = urlparse(p.get("url", "")).path.lower()
        segments = set(url_path.strip("/").split("/"))
        if segments & TAXONOMY_SEGMENTS:
            taxonomy_count += 1
    return taxonomy_count / len(nav_products) >= 0.3


# ── Vertical / audience-segment detection ─────────────────────────────
_VERTICAL_NAMES = {
    # Departments / roles
    "engineering", "sales", "marketing", "it", "hr", "human resources",
    "finance", "operations", "design", "support", "customer service",
    "product management", "security", "legal", "procurement",
    # Industries / verticals
    "healthcare", "education", "government", "retail", "financial services",
    "media", "technology", "manufacturing", "construction", "real estate",
    "nonprofit", "hospitality", "insurance", "automotive", "energy",
    "telecommunications", "logistics", "pharma", "life sciences",
    # Company size segments
    "enterprise", "small business", "smb", "startup", "midmarket",
}


def nav_products_are_verticals(nav_products: List[Dict[str, str]]) -> bool:
    """Return True if ≥40% of nav product names look like audience verticals.

    Audience verticals are department names (Engineering, Sales, Marketing),
    industry segments (Healthcare, Education, Government), or company-size
    segments (Enterprise, SMB).  These are NOT products — they represent
    target audiences or use-case pages.
    """
    if len(nav_products) < 3:
        return False
    vertical_count = 0
    for p in nav_products:
        name = (p.get("name") or "").strip().lower()
        if name in _VERTICAL_NAMES:
            vertical_count += 1
    return vertical_count / len(nav_products) >= 0.4
