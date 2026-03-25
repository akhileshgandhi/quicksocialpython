"""
Pure color-extraction functions for the agentic scraper.

No AI calls, no state mutation — just deterministic extraction from
HTML/CSS, computed styles, logo images, and screenshots.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

import requests

from scraper_agents.config import (
    COLOR_CONFIG,
    THEME_CDN_DOMAINS,
    THIRD_PARTY_WIDGET_RE,
    TIMEOUTS,
)
from scraper_agents.extractors.html_helpers import make_absolute_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Low-level colour helpers
# ---------------------------------------------------------------------------

_NEAR_WHITE = COLOR_CONFIG["near_white_threshold"]   # 220
_GRAY_SPREAD = COLOR_CONFIG["gray_spread_threshold"]  # 25
_GRAY_MIN    = COLOR_CONFIG["gray_brightness_min"]    # 70

# Browser-default link colours — must be rejected everywhere
_BROWSER_DEFAULTS = {"0000EE", "0000FF", "551A8B"}


def _norm_hex(hex_color: str) -> str:
    """Normalise a 3- or 6-digit hex to uppercase 6-digit."""
    h = hex_color.lstrip('#').upper()
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return f"#{h[:6]}"


def _parse_rgb(hex_color: str) -> tuple[int, int, int]:
    """Return (R, G, B) ints from a 6-digit hex string like '#AABBCC'."""
    h = hex_color.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def is_chromatic(hex_color: str) -> bool:
    """True if the colour has meaningful saturation (channel spread >= 25)."""
    try:
        r, g, b = _parse_rgb(hex_color)
        return (max(r, g, b) - min(r, g, b)) >= _GRAY_SPREAD
    except Exception:
        return False


def _is_near_white(hex_color: str) -> bool:
    try:
        r, g, b = _parse_rgb(hex_color)
        return r > _NEAR_WHITE and g > _NEAR_WHITE and b > _NEAR_WHITE
    except Exception:
        return False


def _is_mid_gray(hex_color: str) -> bool:
    try:
        r, g, b = _parse_rgb(hex_color)
        spread = max(r, g, b) - min(r, g, b)
        return spread < _GRAY_SPREAD and r > _GRAY_MIN
    except Exception:
        return False


def filter_boring_colors(hex_colors: List[str]) -> List[str]:
    """Single source of truth for near-white / mid-gray filtering.

    Returns only colours that are neither near-white nor achromatic mid-gray.
    """
    return [c for c in hex_colors if not _is_near_white(c) and not _is_mid_gray(c)]


# Browser default / CSS framework colors that leak through (not real brand colors)
_BROWSER_DEFAULT_COLORS = {
    "#0000EE",  # unvisited link blue
    "#551A8B",  # visited link purple
    "#0000FF",  # blue (default link)
    "#FF0000",  # pure red (error/required)
    "#008000",  # green (success)
    "#CC1122",  # common Shopify sale-badge red
}


def _is_very_near_white(hex_color: str) -> bool:
    """Stricter near-white check: only RGB all > 240 (keeps beiges, pastels)."""
    try:
        r, g, b = _parse_rgb(hex_color)
        return r > 240 and g > 240 and b > 240
    except Exception:
        return False


def filter_boring_colors_relaxed(hex_colors: List[str]) -> List[str]:
    """Relaxed filter for monochrome brands — keeps dark colors and muted tones.

    Only removes: pure/very-near white (#F0F0F0+), and known browser defaults.
    Keeps: blacks, dark grays, earth tones, pastels — all legitimate brand colors
    for minimal/luxury/fashion brands (Sotbella, Apple, Chanel, etc.).
    """
    result = []
    for c in hex_colors:
        norm = c.strip().upper()
        if _is_very_near_white(norm):
            continue
        if norm in _BROWSER_DEFAULT_COLORS:
            continue
        result.append(c)
    return result


# ---------------------------------------------------------------------------
# K-means clustering
# ---------------------------------------------------------------------------

def kmeans_dominant_colors(pixels: "np.ndarray", count: int = 2) -> List[str]:
    """K-means clustering on an Nx3 float32 RGB pixel array.

    Returns up to *count* hex colour strings, excluding near-white and
    mid-gray, with a minimum Euclidean distance of 60 between results.
    """
    import numpy as np

    if len(pixels) < 30:
        return []

    np.random.seed(42)
    k = min(count + 3, 8)
    if len(pixels) < k:
        k = max(len(pixels), 1)
    indices = np.random.choice(len(pixels), k, replace=False)
    centroids = pixels[indices].copy()

    for _ in range(COLOR_CONFIG["kmeans_iterations"]):
        dists = np.linalg.norm(pixels[:, None] - centroids[None, :], axis=2)
        labels = np.argmin(dists, axis=1)
        new_centroids = np.zeros_like(centroids)
        for i in range(k):
            cluster = pixels[labels == i]
            if len(cluster) > 0:
                new_centroids[i] = cluster.mean(axis=0)
            else:
                new_centroids[i] = centroids[i]
        if np.allclose(centroids, new_centroids, atol=1.0):
            break
        centroids = new_centroids

    labels_final = np.argmin(
        np.linalg.norm(pixels[:, None] - centroids[None, :], axis=2), axis=1
    )
    cluster_sizes = [(int(np.sum(labels_final == i)), i) for i in range(k)]
    cluster_sizes.sort(reverse=True)

    MIN_COLOR_DIST = COLOR_CONFIG["kmeans_min_distance"]
    results: List[str] = []
    result_rgbs: List[tuple] = []
    for _, idx in cluster_sizes:
        cr, cg, cb = [int(round(v)) for v in centroids[idx]]
        if cr > _NEAR_WHITE and cg > _NEAR_WHITE and cb > _NEAR_WHITE:
            continue
        if max(cr, cg, cb) - min(cr, cg, cb) < _GRAY_SPREAD and cr > _GRAY_MIN:
            continue
        too_close = False
        for pr, pg, pb in result_rgbs:
            dist = ((cr - pr) ** 2 + (cg - pg) ** 2 + (cb - pb) ** 2) ** 0.5
            if dist < MIN_COLOR_DIST:
                too_close = True
                break
        if too_close:
            continue
        results.append(f"#{cr:02X}{cg:02X}{cb:02X}")
        result_rgbs.append((cr, cg, cb))
        if len(results) >= count:
            break

    return results


# ---------------------------------------------------------------------------
# Logo / screenshot colour extraction
# ---------------------------------------------------------------------------

def extract_colors_from_logo(logo_path: str, count: int = 5) -> List[str]:
    """Extract dominant brand colours from a logo image via K-means.

    Filters transparent, near-white, and mid-gray pixels before clustering.
    Returns up to *count* hex strings (e.g. ``['#2BC5B4', '#1A1A2E']``).
    """
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(logo_path)
        # Strip ICC profile to prevent colour-space shifts (e.g. green
        # logos reporting as blue after CMYK→sRGB re-interpretation).
        if "icc_profile" in img.info:
            img.info.pop("icc_profile")
        img = img.convert("RGBA")
        arr = np.array(img)

        # Filter transparent pixels (alpha < 50)
        alpha = arr[:, :, 3]
        visible = arr[alpha >= 50][:, :3].astype(np.float32)

        if len(visible) < 50:
            return []

        # Filter near-white and mid-gray; keep black/dark (many brands use black)
        r, g, b = visible[:, 0], visible[:, 1], visible[:, 2]
        spread = np.max(visible, axis=1) - np.min(visible, axis=1)
        not_white = ~((r > _NEAR_WHITE) & (g > _NEAR_WHITE) & (b > _NEAR_WHITE))
        not_mid_gray = ~((spread < _GRAY_SPREAD) & (r > _GRAY_MIN) & (r < _NEAR_WHITE))
        colorful = visible[not_white & not_mid_gray]

        if len(colorful) < 30:
            # Retry: keep grays (monochrome logos like Apple, Nike, Chanel)
            colorful = visible[not_white]

        if len(colorful) < 30:
            return []

        results = kmeans_dominant_colors(colorful, count=count)
        logger.info(f"[COLOR] Extracted {len(results)} color(s) from logo: {results}")
        return results

    except Exception as e:
        logger.warning(f"[COLOR] Logo color extraction failed: {e}")
        return []


def extract_colors_from_screenshot_kmeans(screenshot_png: bytes) -> List[str]:
    """Extract dominant brand colours from the header region of a screenshot.

    Crops the top 15 % (header/nav area) and runs K-means clustering.
    Returns up to 2 hex colour strings.
    """
    try:
        from io import BytesIO
        from PIL import Image
        import numpy as np

        img = Image.open(BytesIO(screenshot_png)).convert("RGB")
        w, h = img.size

        # Crop top 15% (header/nav — most reliable brand colour source)
        header_h = max(int(h * 0.15), 60)
        header_crop = img.crop((0, 0, w, header_h))
        arr = np.array(header_crop).reshape(-1, 3).astype(np.float32)

        if len(arr) < 50:
            return []

        r, g, b = arr[:, 0], arr[:, 1], arr[:, 2]
        spread = np.max(arr, axis=1) - np.min(arr, axis=1)
        not_white = ~((r > _NEAR_WHITE) & (g > _NEAR_WHITE) & (b > _NEAR_WHITE))
        not_mid_gray = ~((spread < _GRAY_SPREAD) & (r > _GRAY_MIN) & (r < _NEAR_WHITE))
        colorful = arr[not_white & not_mid_gray]

        if len(colorful) < 30:
            return []

        return kmeans_dominant_colors(colorful, count=2)

    except Exception as e:
        logger.warning(f"[COLOR] Screenshot K-means failed: {e}")
        return []


# ---------------------------------------------------------------------------
# HTML / CSS colour extraction
# ---------------------------------------------------------------------------

# Regex patterns for CSS variable classification
_UTILITY_VAR_RE = re.compile(
    r'(success|error|warning|danger|info|alert|valid|invalid|disabled|'
    r'active|status|badge|positive|negative|approve|reject|pending|'
    r'online|offline|complete|progress|star|rating|review)',
    re.IGNORECASE,
)
_BRAND_VAR_RE = re.compile(
    r'(brand|primary|secondary|accent|theme|main|site|logo|header|nav|cta|button|link)',
    re.IGNORECASE,
)


def extract_colors_comprehensive(soup, base_url: str) -> Dict[str, Any]:
    """Multi-source CSS colour extraction with widget filtering, CDN allowlist,
    and brand/utility classification.

    Returns::

        {
            "colors":         List[str]  — hex colours sorted by brand-relevance,
            "annotated":      str        — human-readable summary with counts/labels,
            "utility_colors": Set[str]   — colours identified as UI utility/state,
        }
    """
    color_counts: Counter = Counter()
    brand_signal_colors: set = set()
    utility_signal_colors: Dict[str, str] = {}  # colour -> label

    def _add(hex_color: str, count: int = 1, brand: bool = False,
             utility_label: Optional[str] = None):
        c = _norm_hex(hex_color)
        color_counts[c] += count
        if brand:
            brand_signal_colors.add(c)
            utility_signal_colors.pop(c, None)
        if utility_label and c not in brand_signal_colors:
            utility_signal_colors[c] = utility_label

    def _scan_css_variables(text: str, brand_weight: int = 3):
        for m in re.finditer(r'--([\w-]+)\s*:\s*(#[0-9A-Fa-f]{6})', text, re.IGNORECASE):
            var_name, hex_val = m.group(1), m.group(2)
            u_match = _UTILITY_VAR_RE.search(var_name)
            b_match = _BRAND_VAR_RE.search(var_name)
            if u_match and not b_match:
                _add(hex_val, count=1, utility_label=u_match.group(1).lower())
            elif b_match:
                _add(hex_val, count=brand_weight, brand=True)
            else:
                _add(hex_val)

    # ── Source 1: <meta name="theme-color"> — strongest brand signal ──
    theme_color = soup.find("meta", attrs={"name": "theme-color"})
    if theme_color and theme_color.get("content"):
        color = theme_color["content"].strip()
        if re.match(r'^#[0-9A-Fa-f]{3,8}$', color):
            _add(color, count=10, brand=True)

    # ── Source 2: <meta name="msapplication-TileColor"> ───────────────
    tile_color = soup.find("meta", attrs={"name": "msapplication-TileColor"})
    if tile_color and tile_color.get("content"):
        color = tile_color["content"].strip()
        if re.match(r'^#[0-9A-Fa-f]{3,8}$', color):
            _add(color, count=5, brand=True)

    # ── Source 3: Inline <style> tags (frequency-counted) ─────────────
    for style in soup.find_all("style"):
        style_text = style.get_text()
        if THIRD_PARTY_WIDGET_RE.search(style_text):
            continue
        for m in re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', style_text):
            _add(m)

    # ── Source 4: Inline style="" on key brand elements ────────────────
    key_selectors = [
        "header", "nav", ".hero", ".banner", ".cta", "button", ".btn",
        "[class*='header']", "[class*='nav']", "[class*='hero']", "[class*='brand']",
    ]
    for sel in key_selectors:
        for elem in soup.select(sel)[:10]:
            inline_style = elem.get("style", "")
            if inline_style:
                for m in re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', inline_style):
                    _add(m, count=2, brand=True)
            for child in elem.find_all(style=True)[:20]:
                child_style = child.get("style", "")
                for m in re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', child_style):
                    _add(m, count=2, brand=True)

    # ── Source 5: CSS custom properties (context-aware) ────────────────
    for style in soup.find_all("style"):
        style_text = style.get_text()
        if THIRD_PARTY_WIDGET_RE.search(style_text):
            continue
        _scan_css_variables(style_text, brand_weight=3)

    # ── Source 6: External stylesheets (same-origin + known CDN) ───────
    try:
        _parsed_base = urlparse(base_url)
        _same_origin = f"{_parsed_base.scheme}://{_parsed_base.netloc}"
        _css_fetched = 0
        for link_tag in soup.find_all("link", rel=lambda x: x and "stylesheet" in " ".join(x).lower()):
            if _css_fetched >= 5:
                break
            css_href = link_tag.get("href", "").strip()
            if not css_href:
                continue
            if css_href.startswith("//") or css_href.startswith("http"):
                _css_domain = urlparse(css_href).netloc.lower()
                _is_same = _same_origin in css_href
                _is_cdn = any(cdn in _css_domain for cdn in THEME_CDN_DOMAINS)
                if not _is_same and not _is_cdn:
                    continue
            css_url = make_absolute_url(css_href, base_url)
            try:
                css_resp = requests.get(
                    css_url,
                    timeout=TIMEOUTS["css_fetch"],
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if css_resp.status_code == 200:
                    css_text = css_resp.text
                    for m in re.findall(r'#[0-9A-Fa-f]{6}(?![0-9A-Fa-f])', css_text):
                        _add(m)
                    _scan_css_variables(css_text, brand_weight=5)
                    _css_fetched += 1
            except Exception:
                pass
    except Exception:
        pass

    # ── Filter boring colours ──────────────────────────────────────────
    filtered = {c: cnt for c, cnt in color_counts.items()
                if not _is_near_white(c) and not _is_mid_gray(c)
                and c.lstrip('#').upper() not in _BROWSER_DEFAULTS}
    if not filtered:
        filtered = {c: cnt for c, cnt in color_counts.items() if not _is_near_white(c)}
    if not filtered and color_counts:
        filtered = dict(color_counts)

    # ── Sort: brand-signal first, chromatic, non-utility, frequency desc
    def _sort_key(item):
        c, cnt = item
        is_brand = 1 if c in brand_signal_colors else 0
        is_utility = 1 if c in utility_signal_colors else 0
        _h = c.lstrip('#').upper()
        is_pure_black = 1 if _h == '000000' else 0
        return (-is_brand, is_pure_black, is_utility, -cnt)

    sorted_colors = sorted(filtered.items(), key=_sort_key)[:15]

    # ── Build annotated string for Gemini ──────────────────────────────
    annotations: List[str] = []
    for c, cnt in sorted_colors:
        parts = [f"x{cnt}"]
        if c in brand_signal_colors:
            parts.append("brand-variable")
        if c in utility_signal_colors:
            parts.append(f"utility: {utility_signal_colors[c]}")
        annotations.append(f"{c} ({', '.join(parts)})")

    return {
        "colors": [c for c, _ in sorted_colors],
        "annotated": "\n".join(annotations) if annotations else "No colors found",
        "utility_colors": set(utility_signal_colors.keys()),
    }


def extract_colors_from_computed(computed_colors: list) -> Dict[str, Any]:
    """Convert Playwright computed-style colour results into the same dict
    shape as :func:`extract_colors_comprehensive`.

    Each entry in *computed_colors* is
    ``{"hex": "#AABBCC", "source": "header-bg", "isBrand": True}``.

    Pure black (``#000000``) is deprioritised below chromatic alternatives.
    """
    if not computed_colors:
        return {"colors": [], "annotated": "No colors found", "utility_colors": set()}

    brand_colors: List[tuple] = []
    non_brand_colors: List[tuple] = []

    for entry in computed_colors:
        hex_val = (entry.get("hex") or "").strip().upper()
        if not hex_val or not hex_val.startswith("#") or len(hex_val) != 7:
            continue
        try:
            r, g, b = _parse_rgb(hex_val)
        except (ValueError, IndexError):
            continue
        # Filter near-white
        if r > _NEAR_WHITE and g > _NEAR_WHITE and b > _NEAR_WHITE:
            continue
        # Filter mid-gray
        spread = max(r, g, b) - min(r, g, b)
        if spread < _GRAY_SPREAD and r > _GRAY_MIN and r < _NEAR_WHITE:
            continue
        # Filter browser default colors (unstyled <a> links)
        if hex_val.lstrip("#") in _BROWSER_DEFAULTS:
            continue

        source = entry.get("source", "")
        is_brand = entry.get("isBrand", False)
        if is_brand:
            brand_colors.append((hex_val, source))
        else:
            non_brand_colors.append((hex_val, source))

    # Within each group, sort chromatic before pure black
    def _black_penalty(item):
        return 1 if item[0] == '#000000' else 0

    brand_colors.sort(key=_black_penalty)
    non_brand_colors.sort(key=_black_penalty)

    # Brand first, then non-brand, deduped
    seen: set = set()
    ordered: List[tuple] = []
    for hex_val, source in brand_colors + non_brand_colors:
        if hex_val not in seen:
            seen.add(hex_val)
            ordered.append((hex_val, source))

    annotations: List[str] = []
    for hex_val, source in ordered:
        label = f"{hex_val} (rendered-dom: {source})"
        if source.startswith("css-var:"):
            label += ", brand-variable"
        annotations.append(label)

    return {
        "colors": [h for h, _ in ordered],
        "annotated": "\n".join(annotations) if annotations else "No colors found",
        "utility_colors": set(),
    }
