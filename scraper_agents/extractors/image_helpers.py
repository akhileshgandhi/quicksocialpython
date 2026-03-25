"""
Pure image/logo helper functions — scoring, ranking, validation, SVG conversion.

No AI calls, no state mutation. All configuration imported from scraper_agents.config.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from PIL import Image

from scraper_agents.config import LOGO_SCORE

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Logo candidate scoring
# ═══════════════════════════════════════════════════════════════════════════

def score_logo_candidate(
    img: Dict[str, Any],
    company_slug: str = "",
    base_url: str = "",
) -> int:
    """
    Multi-signal logo scoring.

    Higher = more likely to be a logo.  Penalties applied for photo-sized
    images, social buttons, white-variant logos, etc.

    *company_slug* is the lowercased, simplified company name
    (e.g. ``"jeevansathi"``) used for affinity bonus / penalty.

    Uses weight constants from ``LOGO_SCORE`` in config where applicable;
    remaining thresholds are kept inline (they are structural, not tunable).
    """
    score = 0

    src = (img.get("src") or "").lower()
    alt = (img.get("alt") or "").lower()
    cls = (img.get("class") or "").lower()

    # ── Keyword signals ───────────────────────────────────────────────
    if "logo" in src:
        score += LOGO_SCORE["keyword_logo"]
    if "logo" in alt:
        score += 4
    if "logo" in cls:
        score += 4
    for kw in ["brand", "site-logo", "header-logo", "nav-logo", "company-logo"]:
        if kw in src or kw in cls:
            score += LOGO_SCORE["keyword_brand"]
            break

    # ── Location signals ──────────────────────────────────────────────
    has_logo_signal = (
        "logo" in src or "logo" in alt or "logo" in cls
        or img.get("is_home_link")
        or img.get("priority_selector")
        or img.get("is_first_in_nav")
    )
    if img.get("in_header"):
        score += 6 if has_logo_signal else 3

    if img.get("is_first_in_nav"):
        score += 5

    # ── Home-link signal ──────────────────────────────────────────────
    if img.get("is_home_link"):
        score += LOGO_SCORE["home_link"]

    # ── External-link penalty ─────────────────────────────────────────
    ancestor_href = img.get("ancestor_href") or ""
    if ancestor_href and "://" in ancestor_href:
        href_domain = urlparse(ancestor_href).netloc.lstrip("www.").lower()
        site_domain = (
            urlparse(base_url).netloc.lstrip("www.").lower() if base_url else ""
        )
        if href_domain and site_domain and href_domain != site_domain:
            score += LOGO_SCORE["external_link_penalty"]  # negative value

    # ── Priority selector signal ──────────────────────────────────────
    if img.get("priority_selector"):
        score += LOGO_SCORE["priority_selector"]

    # ── Format preference / penalty ───────────────────────────────────
    if src.endswith(".svg"):
        score += 3
    elif src.endswith(".webp"):
        score += 2
    elif src.endswith(".jpg") or src.endswith(".jpeg"):
        score -= 4

    # ── Size signals ──────────────────────────────────────────────────
    width = img.get("width") or 0
    height = img.get("height") or 0

    if 30 <= width <= 350:
        score += 4
    elif 350 < width <= 500:
        score += 1
    elif width > 500:
        score -= 12

    if 0 < height <= 150:
        score += 2
    elif height > 300:
        score -= 8

    # ── "icon" keyword penalty ────────────────────────────────────────
    src_filename = src.rsplit("/", 1)[-1] if "/" in src else src
    if "icon" in src_filename and "logo" not in src_filename:
        score += LOGO_SCORE["icon_penalty"]  # negative value

    # ── White/dark variant penalty ────────────────────────────────────
    for variant_kw in ["_white", "-white", "_light", "-light", "white.", "light."]:
        if variant_kw in src_filename.lower():
            score += LOGO_SCORE["white_variant_penalty"]  # negative value
            break

    # ── Penalise likely product / hero photos ─────────────────────────
    for bad_kw in [
        "hero", "banner", "slide", "car-", "product", "feature",
        "vehicle", "jewel", "necklace", "ring", "watch",
        "service", "section", "content", "promo", "campaign",
    ]:
        hit_src = bad_kw in src
        hit_alt = bad_kw in alt and "logo" not in alt
        if hit_src or hit_alt:
            score -= 6
            break

    # ── "Trusted by" / client logo section penalty ────────────────────
    if img.get("in_client_section"):
        return -999  # hard reject — these are OTHER companies' logos, never pick them

    # ── UI element penalty (close/menu/back buttons) ──────────────────
    for ui_kw in [
        "btn-close", "btn-menu", "btn-back", "btn-search",
        "close-btn", "menu-btn", "back-btn", "search-btn",
        "nav-icon", "back-menu", "hamburger", "caret",
        "close-icon", "menu-icon",
    ]:
        if ui_kw in src_filename and "logo" not in src_filename:
            score -= 15
            break

    # ── Social share / widget penalty ─────────────────────────────────
    for social_kw in [
        "whatsapp", "facebook", "instagram", "twitter", "linkedin",
        "youtube", "tiktok", "pinterest", "snapchat", "telegram",
        "button", "badge", "widget", "chat", "share", "appstore",
        "playstore", "googleplay", "app-store", "play-store",
    ]:
        if social_kw in src:
            score -= 10
            break

    # ── Alt-text descriptiveness penalty ──────────────────────────────
    if alt and "logo" not in alt:
        if len(alt.split()) >= 4:
            score -= 4

    # ── Company-name affinity ─────────────────────────────────────────
    if company_slug and len(company_slug) >= 3:
        # Strip domain to inspect only the path + filename
        src_path = src
        if "://" in src:
            src_path = src.split("://", 1)[1]
            src_path = src_path.split("/", 1)[1] if "/" in src_path else ""

        # Strip query params — CDN proxies embed other domains in ?url=...
        src_path_no_query = src_path.split("?")[0]

        slug_in_path = company_slug in src_path_no_query
        slug_in_alt = company_slug in alt
        if slug_in_path or slug_in_alt:
            score += LOGO_SCORE["company_slug_affinity"]

        # Decode proxy URLs (e.g. _next/image/?url=...TaylorMade_logo.jpg)
        # to extract the real filename for foreign-company detection
        src_fn = src_path_no_query.rsplit("/", 1)[-1] if "/" in src_path_no_query else src_path_no_query
        if "url=" in src_path:
            from urllib.parse import unquote
            decoded = unquote(src_path.split("url=", 1)[1].split("&")[0])
            decoded_fn = decoded.rsplit("/", 1)[-1] if "/" in decoded else decoded
            if decoded_fn:
                src_fn = decoded_fn.lower()

        # Penalise "other-company-logo" pattern
        if "logo" in src_fn and not slug_in_path:
            _generic = {
                "logo", "img", "image", "icon", "site", "nav", "header",
                "brand", "png", "jpg", "jpeg", "svg", "webp", "gif",
                "static", "media", "assets", "next", "public", "dark",
                "light", "white", "black", "color", "small", "large",
            }
            other_names = [
                w for w in re.findall(r'[a-z]{3,}', src_fn)
                if w not in _generic and w != "logo"
            ]
            if other_names:
                score += LOGO_SCORE["foreign_company_penalty"]  # negative value

    return score


# ═══════════════════════════════════════════════════════════════════════════
# Logo candidate ranking
# ═══════════════════════════════════════════════════════════════════════════

def rank_logo_candidates(
    candidates: List[Dict[str, Any]],
    base_url: str,
    company_slug: str = "",
) -> List[Tuple[int, str]]:
    """
    Rank images by logo likelihood.

    Returns an ordered list of ``(score, url)`` tuples — highest score first.
    Tie-breaking order: ``is_home_link > is_first_in_nav > has "logo" keyword``.
    """
    scored: List[Tuple[int, int, int, int, str]] = []

    for img in candidates:
        try:
            s = score_logo_candidate(img, company_slug=company_slug, base_url=base_url)
            src = img.get("src")
            if not src:
                continue
            _src_lower = src.lower()
            _alt_lower = (img.get("alt") or "").lower()
            _cls_lower = (img.get("class") or "").lower()
            has_logo_kw = (
                "logo" in _src_lower
                or "logo" in _alt_lower
                or "logo" in _cls_lower
            )
            scored.append((
                s,
                1 if img.get("is_home_link") else 0,
                1 if img.get("is_first_in_nav") else 0,
                1 if has_logo_kw else 0,
                src,
            ))
        except Exception:
            continue

    # Sort by (score DESC, home_link DESC, first_in_nav DESC, logo_kw DESC)
    scored.sort(key=lambda x: (x[0], x[1], x[2], x[3]), reverse=True)

    # Return as (score, url) for backward compatibility
    return [(s, url) for s, _, _, _, url in scored]


# ═══════════════════════════════════════════════════════════════════════════
# Icon detection
# ═══════════════════════════════════════════════════════════════════════════

def is_icon_image(url: str, alt: str = "") -> bool:
    """
    Return ``True`` if the URL / alt text suggest a feature icon rather than
    a company logo.

    Checks for ``"icon"`` in the filename (without ``"logo"``), social-media
    icon filenames, and small square icon naming conventions.
    """
    url_lower = url.lower()
    alt_lower = alt.lower()
    filename = url_lower.rsplit("/", 1)[-1] if "/" in url_lower else url_lower

    # "icon" in filename but not "logo"
    if "icon" in filename and "logo" not in filename:
        return True

    # Common social / UI icon filenames
    _ICON_NAMES = {
        "whatsapp", "facebook", "instagram", "twitter", "linkedin",
        "youtube", "tiktok", "pinterest", "snapchat", "telegram",
        "arrow", "chevron", "hamburger", "menu", "close", "search",
        "cart", "user", "account", "share", "badge",
    }
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    # Strip common prefixes/suffixes
    stem_clean = re.sub(r'[-_]?(icon|img|image|small|large|dark|light|white|black)[-_]?', '', stem)
    if any(name in stem_clean for name in _ICON_NAMES):
        return True

    # Alt text contains "icon" but not "logo"
    if "icon" in alt_lower and "logo" not in alt_lower:
        return True

    return False


# ═══════════════════════════════════════════════════════════════════════════
# Logo image validation
# ═══════════════════════════════════════════════════════════════════════════

def validate_logo_image(
    image_bytes: bytes,
    is_favicon: bool = False,
) -> Dict[str, Any]:
    """
    Validate that downloaded bytes are actually a usable logo image.

    Checks performed:
    - Minimum size (tracking pixel detection)
    - Aspect-ratio sanity (portrait photos, extreme banners)
    - QR-code / barcode detection (OpenCV primary + bimodal fallback)
    - Transparency / blank-image detection
    - Over-size hero/banner rejection (with resize for valid large logos)

    Returns ``{"valid": bool, "reason": str, "width": int, "height": int}``
    and optionally ``"resized_bytes"`` when a valid logo is resized down.
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        width, height = img.size

        # Too small — likely a tracking pixel
        min_dim = 10 if is_favicon else 20
        if width < min_dim or height < min_dim:
            return {
                "valid": False,
                "reason": f"Too small ({width}x{height}px) — likely a tracking pixel",
                "width": width,
                "height": height,
            }

        aspect = width / max(height, 1)

        # ── Shape-based hard rejections ───────────────────────────────
        if aspect < 0.5 and height > 400:
            return {
                "valid": False,
                "reason": (
                    f"Portrait orientation ({width}x{height}px, aspect {aspect:.2f})"
                    " — likely a product photo"
                ),
                "width": width,
                "height": height,
            }
        if aspect < 0.15:
            return {
                "valid": False,
                "reason": f"Too narrow (aspect {aspect:.2f}) — not a logo shape",
                "width": width,
                "height": height,
            }
        if aspect > 20:
            return {
                "valid": False,
                "reason": f"Extreme aspect ratio ({aspect:.2f}) — likely a thin banner strip",
                "width": width,
                "height": height,
            }

        # JPEG small square — e-commerce product thumbnail
        fmt = (img.format or "").upper()
        if fmt in ("JPEG", "JPG") and 0.85 <= aspect <= 1.15 and width <= 150:
            return {
                "valid": False,
                "reason": f"JPEG small square ({width}x{height}px) — likely product thumbnail",
                "width": width,
                "height": height,
            }

        # ── QR code / barcode detection ───────────────────────────────
        if 0.85 <= aspect <= 1.15 and width >= 50:
            _is_qr = False
            # Strategy 1: OpenCV QRCodeDetector
            try:
                import cv2
                import numpy as np

                arr_cv = np.array(img.convert("L"))
                retval, _ = cv2.QRCodeDetector().detect(arr_cv)
                if retval:
                    _is_qr = True
            except Exception:
                pass
            # Strategy 2: bimodal + edge heuristic (fallback)
            if not _is_qr:
                try:
                    import numpy as np

                    gray = img.convert("L")
                    small = gray.resize((200, 200), Image.NEAREST) if width > 200 else gray
                    arr = np.array(small)
                    dark = int(np.sum(arr < 40))
                    light = int(np.sum(arr > 215))
                    total = arr.size
                    bimodal_ratio = (dark + light) / total
                    if bimodal_ratio > 0.80 and dark > 0.15 * total:
                        h_edges = int(np.sum(np.abs(np.diff(arr.astype(np.int16), axis=1)) > 100))
                        v_edges = int(np.sum(np.abs(np.diff(arr.astype(np.int16), axis=0)) > 100))
                        edge_ratio = (h_edges + v_edges) / total
                        if edge_ratio > 0.12:
                            _is_qr = True
                except Exception:
                    pass
            if _is_qr:
                return {
                    "valid": False,
                    "reason": f"QR code / barcode pattern detected ({width}x{height}px)",
                    "width": width,
                    "height": height,
                }

        # ── Mostly-transparent / blank / invisible image ──────────────
        try:
            import numpy as np

            rgba = img.convert("RGBA")
            arr = np.array(rgba)
            alpha = arr[:, :, 3]
            opaque_pixels = int(np.sum(alpha > 25))
            total_pixels = alpha.size
            opaque_ratio = opaque_pixels / total_pixels

            if opaque_ratio < 0.01:
                return {
                    "valid": False,
                    "reason": (
                        f"Image is >99% transparent ({opaque_ratio:.4f} opaque ratio)"
                        " — likely blank/empty"
                    ),
                    "width": width,
                    "height": height,
                }

            # Sparse + monochrome = decorative UI icon
            # BUT: wordmark logos (text-only SVGs on transparent bg) are
            # legitimately sparse. Only reject very tiny coverage (<1.5%).
            if opaque_ratio < 0.015:
                visible = arr[alpha > 25][:, :3]
                if len(visible) > 0:
                    std = float(np.std(visible))
                    if std < 10:
                        return {
                            "valid": False,
                            "reason": (
                                f"Sparse monochrome icon ({opaque_ratio:.2%} coverage,"
                                f" std={std:.1f}) — likely a UI icon, not a logo"
                            ),
                            "width": width,
                            "height": height,
                        }

            # Near-uniform white placeholder
            visible_rgb = arr[alpha > 25][:, :3]
            if len(visible_rgb) > 100:
                r, g, b = visible_rgb[:, 0], visible_rgb[:, 1], visible_rgb[:, 2]
                near_white = int(np.sum((r > 240) & (g > 240) & (b > 240)))
                white_ratio = near_white / len(visible_rgb)
                if white_ratio > 0.95 and opaque_ratio < 0.10:
                    # Check alpha-channel edge complexity before rejecting.
                    # Real white logos (Pepsi swoosh, white text) have intricate
                    # shape edges; blank placeholders are simple uniform blobs.
                    alpha_bin = (alpha > 25).astype(np.uint8)
                    h_edges = int(np.sum(np.abs(np.diff(alpha_bin, axis=1))))
                    v_edges = int(np.sum(np.abs(np.diff(alpha_bin, axis=0))))
                    edge_pixels = h_edges + v_edges
                    edge_ratio = edge_pixels / total_pixels
                    if edge_ratio <= 0.005:
                        return {
                            "valid": False,
                            "reason": (
                                f"Image is {white_ratio:.0%} white with only"
                                f" {opaque_ratio:.1%} coverage — likely a blank placeholder"
                            ),
                            "width": width,
                            "height": height,
                        }
                    logger.info(
                        f"[LOGO] White logo accepted — complex shape edges"
                        f" ({edge_ratio:.4f} edge ratio, {opaque_ratio:.1%} coverage)"
                    )
        except ImportError:
            pass  # numpy not available

        # ── Size checks — resize logo-shaped images instead of rejecting ──
        MAX_LOGO_PX = 1000
        needs_resize = False

        if width > 2000 or height > 2000:
            if height > 400 and aspect < 2.0:
                return {
                    "valid": False,
                    "reason": (
                        f"Large hero/banner image ({width}x{height}px, aspect {aspect:.2f})"
                        " — likely og:image or social share banner, not a logo"
                    ),
                    "width": width,
                    "height": height,
                }
            needs_resize = True
        elif width > 800 and height > 400:
            if aspect < 2.0:
                return {
                    "valid": False,
                    "reason": (
                        f"Ambiguous large image ({width}x{height}px, aspect {aspect:.2f})"
                        " — too close to hero/banner proportions"
                    ),
                    "width": width,
                    "height": height,
                }
            needs_resize = True

        if needs_resize:
            new_w = min(width, MAX_LOGO_PX)
            new_h = int(height * (new_w / width))
            resized = img.resize((new_w, new_h), Image.LANCZOS)
            buf = BytesIO()
            save_fmt = fmt if fmt in ("PNG", "JPEG", "WEBP") else "PNG"
            resized.save(buf, format=save_fmt)
            logger.info(
                f"[LOGO] Resized high-res logo {width}x{height} -> {new_w}x{new_h}px"
            )
            return {
                "valid": True,
                "reason": "OK (resized)",
                "width": new_w,
                "height": new_h,
                "resized_bytes": buf.getvalue(),
            }

        return {"valid": True, "reason": "OK", "width": width, "height": height}

    except Exception as e:
        return {"valid": False, "reason": f"Cannot open as image: {e}", "width": 0, "height": 0}


# ═══════════════════════════════════════════════════════════════════════════
# SVG → PNG conversion
# ═══════════════════════════════════════════════════════════════════════════

def convert_svg_to_png(svg_bytes: bytes, target_size: int = 512) -> Optional[bytes]:
    """
    Convert SVG bytes to PNG.

    Strategy 1: ``cairosvg`` (fast, native C library).
    Strategy 2: Playwright headless Chromium screenshot (run in a thread to
    avoid ``sync_playwright`` inside an async event loop).

    Returns PNG bytes on success, ``None`` on failure.
    """

    # ── Fix BeautifulSoup case-mangling of SVG attributes ─────────────
    _SVG_ATTR_FIXES = {
        b'viewbox=': b'viewBox=',
        b'preserveaspectratio=': b'preserveAspectRatio=',
        b'baseprofile=': b'baseProfile=',
    }
    for wrong, correct in _SVG_ATTR_FIXES.items():
        if wrong in svg_bytes:
            svg_bytes = svg_bytes.replace(wrong, correct)

    # ── Strategy 1: cairosvg ──────────────────────────────────────────
    try:
        import cairosvg

        png_bytes = cairosvg.svg2png(
            bytestring=svg_bytes,
            output_width=target_size,
            output_height=target_size,
        )
        img = Image.open(BytesIO(png_bytes))
        if img.width < 16 or img.height < 16:
            logger.warning("[SVG->PNG] cairosvg result too small, trying Playwright")
        else:
            logger.info(
                f"[SVG->PNG] Converted {len(svg_bytes)}B SVG -> "
                f"{img.width}x{img.height} PNG ({len(png_bytes)}B)"
            )
            return png_bytes
    except ImportError:
        logger.info("[SVG->PNG] cairosvg not available, trying Playwright fallback")
    except Exception as e:
        logger.info(f"[SVG->PNG] cairosvg failed ({e}), trying Playwright fallback")

    # ── Strategy 2: Playwright headless Chromium screenshot ───────────
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        logger.warning(
            "[SVG->PNG] Neither cairosvg nor playwright available — cannot convert SVG"
        )
        return None

    try:
        svg_text = svg_bytes.decode("utf-8", errors="ignore")
        html = (
            '<!DOCTYPE html><html><head><style>'
            'body{margin:0;padding:20px;background:transparent}'
            f'#logo svg{{display:block;max-width:{target_size}px;max-height:{target_size}px;'
            'width:auto;height:auto}}'
            '</style></head><body>'
            f'<div id="logo">{svg_text}</div>'
            '</body></html>'
        )

        def _render() -> Optional[bytes]:
            from playwright.sync_api import sync_playwright as _sp

            pw = _sp().start()
            try:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(
                    viewport={
                        "width": target_size + 40,
                        "height": target_size + 40,
                    }
                )
                page.set_content(html, wait_until="load")
                page.wait_for_timeout(600)
                el = page.query_selector("#logo svg")
                if el and el.bounding_box():
                    png = el.screenshot(type="png", omit_background=True)
                else:
                    el = page.query_selector("#logo")
                    if el and el.bounding_box():
                        png = el.screenshot(type="png", omit_background=True)
                    else:
                        png = page.screenshot(
                            type="png",
                            omit_background=True,
                            clip={
                                "x": 0,
                                "y": 0,
                                "width": target_size,
                                "height": target_size,
                            },
                        )
                browser.close()
                return png
            finally:
                pw.stop()

        # Run in a separate thread to avoid "Sync API inside asyncio loop" error
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            png_bytes = pool.submit(_render).result(timeout=30)

        if png_bytes:
            img = Image.open(BytesIO(png_bytes))
            if img.width < 16 or img.height < 16:
                logger.warning("[SVG->PNG] Playwright result too small")
                return None
            logger.info(
                f"[SVG->PNG] Playwright converted {len(svg_bytes)}B SVG -> "
                f"{img.width}x{img.height} PNG ({len(png_bytes)}B)"
            )
            return png_bytes
        return None
    except Exception as e:
        logger.warning(f"[SVG->PNG] Playwright fallback failed: {e}")
        return None
