"""
VisualIdentityAgent — extracts brand colors and fonts from the website.

Merges colors from multiple sources (logo K-means, Playwright computed styles,
CSS extraction, screenshot K-means) with a clear priority order:
    1. Logo K-means (highest — the logo IS the brand)
    2. Playwright computed DOM colors
    3. CSS / HTML extraction
    4. Screenshot K-means (fallback)

Fonts are extracted from CSS / Google Fonts links and classified by usage
(heading vs body).
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Optional

from scraper_agents.agents.base import BaseAgent
from scraper_agents.state import ScrapeState
from scraper_agents.config import COLOR_CONFIG
from scraper_agents.extractors.color_extraction import (
    extract_colors_comprehensive,
    extract_colors_from_computed,
    extract_colors_from_logo,
    extract_colors_from_screenshot_kmeans,
    filter_boring_colors,
    is_chromatic,
    _hex_to_hsl,
    resolve_brand_palette,
)
from scraper_agents.extractors.font_extraction import extract_fonts_comprehensive

logger = logging.getLogger(__name__)


class VisualIdentityAgent(BaseAgent):
    """Extracts brand colors and fonts from the scraped website."""

    agent_name: str = "visual"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, state: ScrapeState) -> None:
        if not state.homepage_soup:
            self.log("No homepage_soup available — skipping", level="warning")
            return

        # ── Step 1: CSS / HTML color extraction ───────────────────────
        css_result = extract_colors_comprehensive(state.homepage_soup, state.base_url)
        css_colors: List[str] = css_result.get("colors", [])
        brand_signal_css: set = set(css_result.get("brand_signal_colors") or [])
        annotated_parts: List[str] = [css_result.get("annotated", "")]
        utility_colors: set = css_result.get("utility_colors", set())

        self.log(f"CSS extraction found {len(css_colors)} color(s)")

        # ── Step 2: Playwright computed-style colors (if available) ────
        pw_colors: List[str] = []
        if state.pw_computed_colors:
            pw_result = extract_colors_from_computed(state.pw_computed_colors)
            pw_colors = pw_result.get("colors", [])
            if pw_colors:
                self.log(f"Playwright computed styles found {len(pw_colors)} color(s)")
                if pw_result.get("annotated"):
                    annotated_parts.append(pw_result["annotated"])

        # Merge: Playwright colors go first (higher fidelity than static CSS)
        merged_colors = _merge_color_lists(pw_colors, css_colors)

        # ── Step 3: Wait for logo and extract logo K-means colors ─────
        logo_colors: List[str] = []
        try:
            await asyncio.wait_for(state.logo_ready.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            self.log("logo_ready timed out after 20s — proceeding without logo colors")

        if state.logo_bytes and state.logo_local_path:
            logo_colors = extract_colors_from_logo(state.logo_local_path, count=5)
            if logo_colors:
                self.log(f"Logo K-means found {len(logo_colors)} color(s): {logo_colors}")

        # For "brand" sites (FMCG like Dabur, Nike, P&G), the logo IS the
        # brand identity — logo K-means colors are the PRIMARY signal.
        # CSS variables on these sites are often decorative (gold accents,
        # seasonal themes) not the core brand palette.
        # For SaaS/ecommerce/other sites, CSS variables are more reliable
        # because they explicitly declare --primary, --brand, --theme.
        if logo_colors and state.site_type == "brand":
            merged_colors = _merge_color_lists(logo_colors, merged_colors)
            self.log("Brand site — logo colors take priority over CSS")
        elif logo_colors:
            merged_colors = _merge_color_lists(merged_colors, logo_colors)

        # ── Step 4: Screenshot K-means fallback (earlier when few good chroma colors) ─
        screenshot_colors: List[str] = []
        good_colors = filter_boring_colors(merged_colors)
        if len(good_colors) < 3 and state.pw_screenshot:
            screenshot_colors = extract_colors_from_screenshot_kmeans(state.pw_screenshot)
            if screenshot_colors:
                self.log(
                    f"Screenshot K-means fallback found {len(screenshot_colors)} color(s)"
                )
                merged_colors = _merge_color_lists(merged_colors, screenshot_colors)
                good_colors = filter_boring_colors(merged_colors)

        # ── Step 5: Font extraction ───────────────────────────────────
        font_result = extract_fonts_comprehensive(state.homepage_soup, state.base_url)
        fonts: List[Dict[str, Any]] = font_result.get("fonts", [])
        google_fonts_url: Optional[str] = font_result.get("google_fonts_url")
        font_headline_color: Optional[str] = font_result.get("headline_text_color")

        self.log(f"Font extraction found {len(fonts)} font(s)")

        # ── Step 6: Resolve structured brand palette via HSL science ───
        # Extract CTA/button colours from Playwright (accent candidates)
        cta_colors = [
            c.get("hex", "") for c in (state.pw_computed_colors or [])
            if c.get("source", "").startswith("button")
        ]

        website_color_counts = Counter(
            c.strip().upper()
            for c in (pw_colors + css_colors + screenshot_colors)
            if c
        )
        merged_colors = _filter_noise_colors(
            merged_colors,
            website_color_counts=website_color_counts,
            logo_colors=logo_colors,
            cta_colors=cta_colors,
            brand_signal_colors=brand_signal_css,
        )
        good_colors = filter_boring_colors(merged_colors)

        palette, color_audit_core = resolve_brand_palette(
            logo_colors=logo_colors,
            website_colors=good_colors or merged_colors,
            cta_colors=cta_colors,
            site_type=state.site_type,
        )
        state.color_audit = {
            **color_audit_core,
            "candidates": {
                "logo_kmeans": list(logo_colors),
                "playwright_computed": list(pw_colors),
                "css_html": list(css_colors),
                "cta_playwright": [c for c in cta_colors if c],
                "screenshot_kmeans": list(screenshot_colors),
                "merged_pre_resolve": list(good_colors or merged_colors)[:40],
            },
            "brand_signal_css": sorted(brand_signal_css, key=lambda x: x.upper()),
        }

        # Build primary_color list for backward compatibility:
        # [primary, secondary, accent, background, text]
        brand_colors = [
            palette["primary"],
            palette["secondary"],
            palette["accent"],
            palette["background"],
            palette["text"],
        ]
        # Remove duplicates while preserving order
        seen_bc: set = set()
        brand_colors_deduped: List[str] = []
        for c in brand_colors:
            if c and c not in seen_bc:
                seen_bc.add(c)
                brand_colors_deduped.append(c)

        headline_text_color = font_headline_color  # from CSS heading rules
        if not headline_text_color:
            headline_text_color = palette["text"]

        # Resolve headline + body fonts
        headline_font, body_font = _resolve_fonts(fonts)

        # Merge Playwright computed fonts (higher priority — JS-rendered)
        if state.pw_computed_fonts:
            for pf in state.pw_computed_fonts:
                fam = pf.get("family", "").strip()
                usage = pf.get("usage", "unknown")
                if not fam or _is_icon_font(fam):
                    continue
                if usage == "heading" and not headline_font:
                    headline_font = fam
                elif usage == "body" and not body_font:
                    body_font = fam

        # ── Step 7: Write results to state ────────────────────────────
        state.primary_color = brand_colors_deduped or None
        state.secondary_color = None                # Deprecated
        state.headline_text_color = headline_text_color
        state.brand_palette = palette               # New structured palette

        state.headline_font = headline_font
        state.body_font = body_font
        state.google_fonts_url = google_fonts_url
        state.fonts_data = fonts

        state.colors_found = merged_colors[:15]
        state.colors_utility = utility_colors
        state.colors_annotated = "\n".join(
            part for part in annotated_parts if part and part != "No colors found"
        ) or "No colors found"

        self.log(
            f"Resolved palette: primary={palette['primary']} "
            f"secondary={palette['secondary']} accent={palette['accent']}, "
            f"headline_font={headline_font}, body_font={body_font}"
        )


# ======================================================================
# Private helpers
# ======================================================================


def _merge_color_lists(high_priority: List[str], low_priority: List[str]) -> List[str]:
    """Merge two color lists with deduplication, preserving order.

    Colors from *high_priority* appear first; duplicates from
    *low_priority* are dropped.
    """
    seen: set = set()
    merged: List[str] = []
    for c in high_priority:
        norm = c.strip().upper()
        if norm and norm not in seen:
            seen.add(norm)
            merged.append(norm)
    for c in low_priority:
        norm = c.strip().upper()
        if norm and norm not in seen:
            seen.add(norm)
            merged.append(norm)
    return merged


def _is_noise_color(hex_color: str) -> bool:
    """Return True for desaturated or washed-out website colours."""
    _, s, l = _hex_to_hsl(hex_color)
    return (
        s < 10 or
        l > 95 or
        (20 < l < 80 and s < 15)
    )


def _filter_noise_colors(
    merged_colors: List[str],
    website_color_counts: Counter[str],
    logo_colors: List[str],
    cta_colors: List[str],
    brand_signal_colors: Optional[set] = None,
) -> List[str]:
    """Filter website-only noise while preserving logo, CTA, and CSS brand-token colours."""
    logo_set = {c.strip().upper() for c in logo_colors if c}
    cta_set = {c.strip().upper() for c in cta_colors if c}
    brand_set = {c.strip().upper() for c in (brand_signal_colors or set()) if c}

    filtered: List[str] = []
    for color in merged_colors:
        norm = color.strip().upper()
        if not norm:
            continue
        if norm in logo_set or norm in cta_set or norm in brand_set:
            filtered.append(norm)
            continue
        if website_color_counts.get(norm, 0) <= 1:
            continue
        if _is_noise_color(norm):
            continue
        filtered.append(norm)

    return filtered


def _resolve_brand_colors(
    good_colors: List[str],
    all_colors: List[str],
    logo_colors: List[str],
) -> List[str]:
    """Return ALL logo colors + 1 most dominant website color as the brand palette.

    Logo colours are the most reliable brand signal — they ALL go in.
    Then one dominant chromatic colour from the website (CSS/Playwright) is
    appended to round out the palette.
    """
    result: List[str] = []
    seen: set = set()

    # 1. Add all logo colors first (the core brand signal)
    for c in logo_colors:
        norm = c.strip().upper()
        if norm and norm not in seen:
            seen.add(norm)
            result.append(norm)

    # 2. Add 1 dominant website color (first chromatic non-logo color)
    candidates = good_colors if good_colors else all_colors
    for c in candidates:
        norm = c.strip().upper()
        if norm not in seen and is_chromatic(norm):
            result.append(norm)
            break

    # Fallback: if nothing at all, take the first available color
    if not result and all_colors:
        result.append(all_colors[0].strip().upper())

    return result


_ICON_FONT_KW = {"icon", "glyph", "symbol", "awesome", "icomoon", "material",
                  "fontello", "fontisto", "ionicon", "feather", "linearicon"}


def _is_icon_font(name: str) -> bool:
    """Return True if *name* looks like an icon/symbol font."""
    low = name.lower()
    return any(kw in low for kw in _ICON_FONT_KW)


def _resolve_fonts(
    fonts: List[Dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """Pick headline and body fonts from the extracted font list.

    Priority:
    1. Fonts explicitly tagged with usage="heading" / usage="body"
    2. First Google Fonts entry for headline, second for body
    3. First two fonts in the list

    Icon/symbol fonts (Glyphicons, FontAwesome, etc.) are always skipped.
    """
    headline_font: Optional[str] = None
    body_font: Optional[str] = None

    # Pass 1: look for explicit usage tags
    for f in fonts:
        usage = (f.get("usage") or "").lower()
        family = f.get("family", "")
        if not family or _is_icon_font(family):
            continue
        if usage == "heading" and not headline_font:
            headline_font = family
        elif usage == "body" and not body_font:
            body_font = family

    # Pass 2: fallback to Google Fonts entries
    if not headline_font or not body_font:
        google_fonts = [
            f["family"] for f in fonts
            if f.get("source") == "google_fonts" and f.get("family")
            and not _is_icon_font(f["family"])
        ]
        if not headline_font and google_fonts:
            headline_font = google_fonts[0]
        if not body_font and len(google_fonts) >= 2:
            body_font = google_fonts[1]

    # Pass 3: fallback to first available fonts
    if not headline_font or not body_font:
        all_families = [
            f["family"] for f in fonts
            if f.get("family") and not _is_icon_font(f["family"])
        ]
        if not headline_font and all_families:
            headline_font = all_families[0]
        if not body_font and len(all_families) >= 2:
            # Pick one that differs from headline
            for fam in all_families:
                if fam != headline_font:
                    body_font = fam
                    break

    return headline_font, body_font
