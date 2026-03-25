"""
Pure-function extractors for content assets (files, case studies,
testimonials, blog posts, videos, galleries) and detail-page enrichment.

Ported from scraper.py — no AI calls, no state mutation.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import re
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

from ..config import CONCURRENCY, TIMEOUTS, DEFAULT_HEADERS
from .html_helpers import make_absolute_url, get_img_src

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_item_link(item) -> str | None:
    """Find the link for a content item — check child <a> first, then
    check if the item itself or an ancestor is an <a> with href.

    Many modern sites (Next.js, React) wrap the entire card in ``<a>``.
    """
    link = item.find("a", href=True)
    if link:
        return link["href"]
    if item.name == "a" and item.get("href"):
        return item["href"]
    # Walk up ancestors (up to 3 levels) to find wrapping <a>
    node = item
    for _ in range(3):
        node = node.parent
        if not node or node.name in ("[document]", "body", "html"):
            break
        if node.name == "a" and node.get("href"):
            return node["href"]
    return None


# ---------------------------------------------------------------------------
# Public API — extraction
# ---------------------------------------------------------------------------

def extract_content_assets(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    """Extract content assets from a page.

    Scans for downloadable files (.pdf, .docx, …), case studies,
    testimonials, blog posts, videos (YouTube / Vimeo), and gallery images.

    Returns a list of dicts with keys:
        title, asset_type, url, thumbnail_url, description, download_url, file_type
    """
    assets: List[Dict[str, Any]] = []
    seen_urls: set = set()
    seen_titles: Dict[str, int] = {}  # title_lower → index in assets

    # -- dedup / add helper (closure over assets/seen_*) --------------------

    def _add_asset(
        title: str,
        asset_type: str,
        url: str | None = None,
        thumbnail_url: str | None = None,
        description: str | None = None,
        file_type: str | None = None,
    ) -> None:
        # Skip data: URIs (SVG placeholders, base64 images)
        if url and url.startswith("data:"):
            return
        if thumbnail_url and thumbnail_url.startswith("data:"):
            thumbnail_url = None
        if url and url in seen_urls:
            return
        if not title or len(title.strip()) < 2:
            return

        clean_title = title.strip()[:200]
        title_key = clean_title.lower()

        # Deduplicate by title — upgrade existing entry if the new one has more data
        if title_key in seen_titles:
            idx = seen_titles[title_key]
            existing = assets[idx]
            if url and not existing["url"]:
                existing["url"] = url
                seen_urls.add(url)
            if thumbnail_url and not existing["thumbnail_url"]:
                existing["thumbnail_url"] = thumbnail_url
            if description and not existing["description"]:
                existing["description"] = description[:300]
            if file_type and not existing["file_type"]:
                existing["file_type"] = file_type
            return

        if url:
            seen_urls.add(url)
        seen_titles[title_key] = len(assets)
        assets.append({
            "title": clean_title,
            "asset_type": asset_type,
            "url": url,
            "thumbnail_url": thumbnail_url,
            "description": description[:300] if description else None,
            "file_type": file_type,
        })

    # ── 1. Downloadable files (PDF, DOCX, XLSX, PPTX, ZIP, …) ────────────
    file_extensions = {
        ".pdf": "pdf", ".docx": "docx", ".xlsx": "xlsx",
        ".pptx": "pptx", ".zip": "zip", ".csv": "csv",
        ".xls": "xls", ".doc": "doc", ".ppt": "ppt",
    }
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].lower().split("?")[0].split("#")[0]
        for ext, ftype in file_extensions.items():
            if href.endswith(ext):
                abs_url = make_absolute_url(a_tag["href"], base_url)
                link_text = a_tag.get_text(strip=True)
                parent = a_tag.find_parent(["section", "div", "article", "li"])
                heading = parent.find(["h1", "h2", "h3", "h4", "h5"]) if parent else None
                title = (
                    link_text
                    or (heading.get_text(strip=True) if heading else "")
                    or os.path.basename(a_tag["href"])
                )
                _add_asset(
                    title,
                    ftype if ftype == "pdf" else "document",
                    url=abs_url,
                    file_type=ftype,
                )
                break

    # ── 2. Case studies / Portfolio / Success stories ─────────────────────
    case_study_kw = [
        "case-stud", "case_stud", "success-stor", "success_stor",
        "portfolio", "our-work", "our_work", "project", "client-stor",
    ]
    for section in soup.find_all(["section", "div", "article"]):
        cls_id = (
            " ".join(section.get("class", [])) + " " + (section.get("id") or "")
        ).lower()
        if not any(kw in cls_id for kw in case_study_kw):
            continue
        items = section.find_all(
            ["article", "div", "a"],
            recursive=True,
            class_=lambda c: c and any(
                k in " ".join(c).lower()
                for k in ["card", "item", "entry", "post"]
            ),
        )
        if not items:
            items = section.find_all(["article", "li"], recursive=True)
        for item in items[:10]:
            heading = item.find(["h2", "h3", "h4", "h5"])
            if not heading:
                continue
            title = heading.get_text(strip=True)
            href = _find_item_link(item)
            url = make_absolute_url(href, base_url) if href else None
            img = item.find("img")
            thumb = (
                make_absolute_url(get_img_src(img), base_url)
                if img and get_img_src(img)
                else None
            )
            desc_p = item.find("p")
            desc = desc_p.get_text(strip=True) if desc_p else None
            asset_type = "portfolio_item" if "portfolio" in cls_id else "case_study"
            _add_asset(title, asset_type, url=url, thumbnail_url=thumb, description=desc)
        if not items:
            heading = section.find(["h2", "h3"])
            if heading:
                link = section.find("a", href=True)
                _add_asset(
                    heading.get_text(strip=True),
                    "case_study",
                    url=make_absolute_url(link["href"], base_url) if link else None,
                )

    # ── 3. Testimonials / Reviews ─────────────────────────────────────────
    testimonial_kw = [
        "testimonial", "review", "feedback", "client-say",
        "customer-say", "what-people", "quote",
    ]
    for section in soup.find_all(["section", "div"]):
        cls_id = (
            " ".join(section.get("class", [])) + " " + (section.get("id") or "")
        ).lower()
        if not any(kw in cls_id for kw in testimonial_kw):
            continue
        quotes = section.find_all(
            ["blockquote", "div", "p"],
            class_=lambda c: c and any(
                k in " ".join(c).lower()
                for k in ["quote", "testimonial", "review", "feedback"]
            ),
        )
        if not quotes:
            quotes = section.find_all("blockquote")
        for q in quotes[:8]:
            text = q.get_text(strip=True)
            if len(text) < 15:
                continue
            cite = q.find(
                ["cite", "span", "strong", "p"],
                class_=lambda c: c and any(
                    k in " ".join(c).lower()
                    for k in ["author", "name", "cite", "attribution"]
                ),
            )
            author = cite.get_text(strip=True) if cite else None
            title = f"Testimonial from {author}" if author else text[:80]
            _add_asset(title, "testimonial", description=text[:300])

    # ── 4. Blog / News highlights ─────────────────────────────────────────
    blog_kw = ["blog", "news", "article", "insight", "update", "press"]
    for section in soup.find_all(["section", "div"]):
        cls_id = (
            " ".join(section.get("class", [])) + " " + (section.get("id") or "")
        ).lower()
        if not any(kw in cls_id for kw in blog_kw):
            continue
        posts = section.find_all(
            ["article", "div", "a"],
            class_=lambda c: c and any(
                k in " ".join(c).lower()
                for k in ["card", "post", "entry", "item", "article"]
            ),
        )
        if not posts:
            posts = section.find_all("article", recursive=True)
        for post in posts[:5]:
            heading = post.find(["h2", "h3", "h4", "h5"])
            if not heading:
                continue
            title = heading.get_text(strip=True)
            href = _find_item_link(post)
            url = make_absolute_url(href, base_url) if href else None
            img = post.find("img")
            thumb = (
                make_absolute_url(get_img_src(img), base_url)
                if img and get_img_src(img)
                else None
            )
            _add_asset(title, "blog_post", url=url, thumbnail_url=thumb)

    # ── 4b. Link-based blog / case study discovery ────────────────────────
    link_patterns = {
        "/blog/": "blog_post",
        "/case-stud": "case_study",
        "/case_stud": "case_study",
        "/portfolio/": "portfolio_item",
        "/success-stor": "case_study",
    }
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        href_lower = href.lower()
        for pattern, atype in link_patterns.items():
            if pattern in href_lower and href_lower.rstrip("/") != pattern.rstrip("/"):
                abs_url = make_absolute_url(href, base_url)
                if abs_url in seen_urls:
                    break
                link_text = a_tag.get_text(strip=True)
                title = re.sub(
                    r"^(new|latest|featured)\s+", "", link_text, flags=re.IGNORECASE
                ).strip()
                title = re.sub(r"\s*[->]+\s*$", "", title).strip()
                if title and len(title) > 5:
                    _add_asset(title, atype, url=abs_url)
                break

    # ── 5. Videos (YouTube / Vimeo embeds and <video> tags) ───────────────
    video_providers = {
        "youtube.com": "youtube",
        "youtu.be": "youtube",
        "vimeo.com": "vimeo",
        "wistia.com": "wistia",
    }
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"]
        for provider_domain, provider in video_providers.items():
            if provider_domain in src:
                abs_url = make_absolute_url(src, base_url)
                title = iframe.get("title", "") or f"{provider.title()} video"
                _add_asset(title, "video", url=abs_url)
                break
    for video_tag in soup.find_all("video"):
        src = video_tag.get("src") or ""
        source = video_tag.find("source")
        if not src and source:
            src = source.get("src", "")
        if src:
            abs_url = make_absolute_url(src, base_url)
            _add_asset(
                video_tag.get("title", "Video"), "video", url=abs_url, file_type="mp4"
            )

    # ── 6. Gallery / Lightbox sections ────────────────────────────────────
    gallery_kw = ["gallery", "lightbox", "photo", "image-grid", "masonry"]
    for section in soup.find_all(["section", "div"]):
        cls_id = (
            " ".join(section.get("class", [])) + " " + (section.get("id") or "")
        ).lower()
        if not any(kw in cls_id for kw in gallery_kw):
            continue
        imgs = section.find_all("img")
        for img in imgs[:15]:
            src = get_img_src(img)
            if not src:
                continue
            abs_url = make_absolute_url(src, base_url)
            w = int(img.get("width", 0) or 0) if str(img.get("width", "")).isdigit() else 0
            h = int(img.get("height", 0) or 0) if str(img.get("height", "")).isdigit() else 0
            if (w and w < 50) or (h and h < 50):
                continue
            alt = img.get("alt", "") or "Gallery image"
            _add_asset(alt, "gallery_image", url=abs_url)

    return assets


# ---------------------------------------------------------------------------
# Public API — enrichment
# ---------------------------------------------------------------------------

# File extensions recognised as direct downloads
_DOWNLOAD_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".zip", ".rar", ".csv", ".epub",
}

# Keywords in href or button text that signal a download action
_DOWNLOAD_KEYWORDS = {
    "download", "get-pdf", "get_pdf", "export", "save-as", "save_as",
}

# Direct-file extensions that should not be fetched as HTML pages
_DIRECT_FILE_EXTENSIONS = (
    ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".mp4", ".mp3",
)


def enrich_content_assets(
    assets: List[Dict[str, Any]],
    base_url: str,
    headers: dict | None = None,
    max_pages: int | None = None,
) -> List[Dict[str, Any]]:
    """Follow each content-asset URL to extract thumbnail, description, download link.

    Uses ``ThreadPoolExecutor`` for concurrent fetches.  Per-page results are
    collected in an isolated dict and merged back — the shared *assets* list
    is never mutated from worker threads.

    Parameters
    ----------
    assets:
        The list returned by :func:`extract_content_assets`.
    base_url:
        The originating page URL (used for resolving relative links).
    headers:
        HTTP headers for requests.  Falls back to ``DEFAULT_HEADERS``.
    max_pages:
        Cap on the number of detail pages to fetch.  Falls back to
        ``CONCURRENCY["max_asset_enrichments"]``.
    """
    if headers is None:
        headers = dict(DEFAULT_HEADERS)
    if max_pages is None:
        max_pages = CONCURRENCY["max_asset_enrichments"]

    fetch_timeout = TIMEOUTS.get("asset_enrich_fetch", 12)
    max_workers = CONCURRENCY.get("asset_enrich_workers", 4)

    # Identify assets worth enriching
    to_enrich: List[tuple] = []
    for i, asset in enumerate(assets):
        url = asset.get("url")
        if not url:
            continue
        # Skip if already fully populated
        if (
            asset.get("thumbnail_url")
            and asset.get("description")
            and asset.get("download_url")
        ):
            continue
        # Direct-file URLs: populate file_type/download_url in-place, skip fetch
        url_lower = url.lower()
        if any(url_lower.endswith(ext) for ext in _DIRECT_FILE_EXTENSIONS):
            ext = url_lower.rsplit(".", 1)[-1]
            if not asset.get("file_type"):
                asset["file_type"] = ext
            if not asset.get("download_url"):
                asset["download_url"] = url
            continue
        to_enrich.append((i, url))

    if not to_enrich:
        return assets

    to_enrich = to_enrich[:max_pages]
    logger.info(f"   [ENRICH] Enriching {len(to_enrich)} content asset detail pages...")

    # -- worker (pure function — no shared-list mutation) -------------------

    def _fetch_and_extract(idx_url: tuple) -> tuple:
        idx, page_url = idx_url
        result: Dict[str, Any] = {
            "thumbnail_url": None,
            "description": None,
            "download_url": None,
            "file_type": None,
        }
        try:
            resp = requests.get(
                page_url, headers=headers, timeout=fetch_timeout, allow_redirects=True
            )
            if resp.status_code != 200:
                return idx, result
            page_soup = BeautifulSoup(resp.text, "html.parser")

            # --- 1. THUMBNAIL ---
            og_img = page_soup.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                result["thumbnail_url"] = make_absolute_url(
                    og_img["content"].strip(), page_url
                )
            else:
                tw_img = page_soup.find("meta", attrs={"name": "twitter:image"})
                if tw_img and tw_img.get("content"):
                    result["thumbnail_url"] = make_absolute_url(
                        tw_img["content"].strip(), page_url
                    )
                else:
                    main_el = (
                        page_soup.find("article")
                        or page_soup.find("main")
                        or page_soup.find("section")
                    )
                    if main_el:
                        for img in main_el.find_all("img", limit=10):
                            src = get_img_src(img)
                            if not src or src.startswith("data:"):
                                continue
                            w = (
                                int(img.get("width", 0) or 0)
                                if str(img.get("width", "")).isdigit()
                                else 0
                            )
                            h = (
                                int(img.get("height", 0) or 0)
                                if str(img.get("height", "")).isdigit()
                                else 0
                            )
                            if (w and w < 100) or (h and h < 100):
                                continue
                            alt_lower = (img.get("alt") or "").lower()
                            if any(
                                kw in alt_lower
                                for kw in ["icon", "arrow", "chevron", "logo", "avatar"]
                            ):
                                continue
                            result["thumbnail_url"] = make_absolute_url(src, page_url)
                            break

            # --- 2. DESCRIPTION ---
            og_desc = page_soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content") and len(og_desc["content"].strip()) > 20:
                result["description"] = og_desc["content"].strip()[:300]
            else:
                meta_desc = page_soup.find("meta", attrs={"name": "description"})
                if (
                    meta_desc
                    and meta_desc.get("content")
                    and len(meta_desc["content"].strip()) > 20
                ):
                    result["description"] = meta_desc["content"].strip()[:300]
                else:
                    content_el = (
                        page_soup.find("article")
                        or page_soup.find("main")
                        or page_soup.find("section")
                    )
                    if content_el:
                        for p in content_el.find_all("p", limit=10):
                            text = p.get_text(strip=True)
                            if len(text) > 40:
                                result["description"] = text[:300]
                                break

            # --- 3. DOWNLOAD LINKS ---
            for a_tag in page_soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                href_lower = href.lower()
                link_text = a_tag.get_text(strip=True).lower()

                href_path = href_lower.split("?")[0].split("#")[0]
                matched_ext = None
                for ext in _DOWNLOAD_EXTENSIONS:
                    if href_path.endswith(ext):
                        matched_ext = ext.lstrip(".")
                        break

                if matched_ext:
                    result["download_url"] = make_absolute_url(href, page_url)
                    result["file_type"] = matched_ext
                    break

                if any(kw in link_text for kw in _DOWNLOAD_KEYWORDS) or any(
                    kw in href_lower for kw in _DOWNLOAD_KEYWORDS
                ):
                    if (
                        a_tag.get("download") is not None
                        or "pdf" in link_text
                        or "pdf" in href_lower
                    ):
                        result["download_url"] = make_absolute_url(href, page_url)
                        result["file_type"] = (
                            "pdf" if "pdf" in (link_text + href_lower) else None
                        )
                        break

            # If no <a> download found, check <button> with onclick / data-href
            if not result["download_url"]:
                for btn in page_soup.find_all(["button", "a"], limit=50):
                    btn_text = btn.get_text(strip=True).lower()
                    if "download" not in btn_text:
                        continue
                    for attr in ("data-href", "data-url", "data-link"):
                        val = btn.get(attr)
                        if val:
                            result["download_url"] = make_absolute_url(
                                val.strip(), page_url
                            )
                            val_lower = val.lower()
                            for ext in _DOWNLOAD_EXTENSIONS:
                                if val_lower.endswith(ext):
                                    result["file_type"] = ext.lstrip(".")
                                    break
                            if not result["file_type"] and "pdf" in btn_text:
                                result["file_type"] = "pdf"
                            break
                    if result["download_url"]:
                        break
                    # Check onclick for URL
                    onclick = btn.get("onclick", "")
                    if onclick:
                        url_match = re.search(
                            r"""(?:window\.open|location\.href|window\.location)\s*[=(]\s*['"]([^'"]+)""",
                            onclick,
                        )
                        if url_match:
                            result["download_url"] = make_absolute_url(
                                url_match.group(1), page_url
                            )
                            if "pdf" in btn_text or ".pdf" in url_match.group(1).lower():
                                result["file_type"] = "pdf"
                            break

        except Exception as e:
            logger.debug(f"   [ENRICH] Failed to enrich {page_url}: {e}")

        return idx, result

    # -- dispatch concurrent fetches ----------------------------------------

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_and_extract, item): item for item in to_enrich
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                idx, result = future.result()
                asset = assets[idx]
                if result["thumbnail_url"] and not asset.get("thumbnail_url"):
                    asset["thumbnail_url"] = result["thumbnail_url"]
                if result["description"] and not asset.get("description"):
                    asset["description"] = result["description"]
                if result["download_url"] and not asset.get("download_url"):
                    asset["download_url"] = result["download_url"]
                if result["file_type"] and not asset.get("file_type"):
                    asset["file_type"] = result["file_type"]
            except Exception as e:
                logger.debug(f"   [ENRICH] Thread error: {e}")

    # -- log enrichment stats -----------------------------------------------
    thumbs = sum(1 for i, _ in to_enrich if assets[i].get("thumbnail_url"))
    descs = sum(1 for i, _ in to_enrich if assets[i].get("description"))
    downloads = sum(1 for i, _ in to_enrich if assets[i].get("download_url"))
    logger.info(
        f"   [ENRICH] Done — thumbnails: {thumbs}, descriptions: {descs}, downloads: {downloads}"
    )

    return assets
