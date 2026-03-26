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
    filter_boring_colors_relaxed,
    is_chromatic,
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
            await asyncio.wait_for(state.logo_ready.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            self.log("logo_ready timed out after 30s — proceeding without logo colors")

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

        # ── Step 4: Screenshot K-means fallback ───────────────────────
        good_colors = filter_boring_colors(merged_colors)
        if len(good_colors) < 2 and state.pw_screenshot:
            screenshot_colors = extract_colors_from_screenshot_kmeans(state.pw_screenshot)
            if screenshot_colors:
                self.log(
                    f"Screenshot K-means fallback found {len(screenshot_colors)} color(s)"
                )
                merged_colors = _merge_color_lists(merged_colors, screenshot_colors)
                good_colors = filter_boring_colors(merged_colors)

        # ── Step 4b: Relaxed filter for monochrome brands ───────────
        # If strict filter leaves ≤1 color, the brand is likely monochrome
        # (fashion, luxury, minimal). Use relaxed filter that keeps dark
        # colors and earth tones — these ARE the brand identity.
        if len(good_colors) <= 1:
            relaxed = filter_boring_colors_relaxed(merged_colors)
            if len(relaxed) > len(good_colors):
                self.log(f"Monochrome brand — relaxed filter found {len(relaxed)} color(s)")
                good_colors = relaxed

        # ── Step 5: Font extraction ───────────────────────────────────
        font_result = extract_fonts_comprehensive(state.homepage_soup, state.base_url)
        fonts: List[Dict[str, Any]] = font_result.get("fonts", [])
        google_fonts_url: Optional[str] = font_result.get("google_fonts_url")
        font_headline_color: Optional[str] = font_result.get("headline_text_color")

        # Merge Playwright computed fonts (highest priority — actual rendered fonts)
        if state.pw_computed_fonts:
            existing_families = {f.get("family", "").lower() for f in fonts}
            for pf in state.pw_computed_fonts:
                family = pf.get("family", "")
                if family.lower() not in existing_families:
                    fonts.insert(0, pf)  # prepend — computed fonts get priority
                    existing_families.add(family.lower())
                else:
                    # Update usage if CSS-only had "unknown" but computed knows the role
                    for f in fonts:
                        if f.get("family", "").lower() == family.lower():
                            if f.get("usage") == "unknown" and pf.get("usage") != "unknown":
                                f["usage"] = pf["usage"]
                            break

        self.log(f"Font extraction found {len(fonts)} font(s)")

        # ── Step 6: Resolve brand color palette + headline color ───────
        brand_colors = _resolve_brand_colors(good_colors, merged_colors, logo_colors)

        headline_text_color = font_headline_color  # from CSS heading rules
        if not headline_text_color and brand_colors:
            headline_text_color = brand_colors[0]

        # Resolve headline + body fonts
        headline_font, body_font = _resolve_fonts(fonts)

        # ── Step 7: Write results to state ────────────────────────────
        state.primary_color = brand_colors or None  # List[str]
        state.secondary_color = None                # Deprecated
        state.headline_text_color = headline_text_color

        state.headline_font = headline_font
        state.body_font = body_font
        state.google_fonts_url = google_fonts_url
        state.fonts_data = fonts

        state.colors_found = merged_colors[:15]
        state.colors_utility = utility_colors
        # Build combined annotated string
        state.colors_annotated = "\n".join(
            part for part in annotated_parts if part and part != "No colors found"
        ) or "No colors found"

        self.log(
            f"Resolved brand_colors={brand_colors}, "
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

# Known real fonts — if a font name is in this set, it's never a brand-custom font
_KNOWN_REAL_FONTS = {
    "open sans", "roboto", "lato", "montserrat", "poppins", "inter", "raleway",
    "nunito", "playfair display", "merriweather", "oswald", "source sans pro",
    "pt sans", "noto sans", "ubuntu", "mukta", "rubik", "work sans", "dosis",
    "quicksand", "dm sans", "barlow", "josefin sans", "libre baskerville",
    "jost", "geist", "outfit", "space grotesk", "plus jakarta sans", "figtree",
    "manrope", "urbanist", "lexend", "be vietnam pro", "sora", "archivo",
    "cabin", "karla", "mulish", "exo", "fira sans", "ibm plex sans",
    "crimson text", "bitter", "cormorant", "spectral", "alegreya",
    "source serif pro", "eb garamond", "libre franklin", "hind", "titillium web",
    "mier", "mierb", "mierb-regular", "mierb-demibold",
}


def _is_icon_font(name: str) -> bool:
    """Return True if *name* looks like an icon/symbol font."""
    low = name.lower()
    return any(kw in low for kw in _ICON_FONT_KW)


def _is_brand_custom_font(name: str) -> bool:
    """Return True if *name* looks like a brand-specific display font (e.g., 'Lays', 'Nike').

    Brand-custom fonts are single-word names that are NOT known real fonts.
    They shouldn't be used as body_font since they're display/logo fonts only.
    """
    low = name.strip().lower()
    if low in _KNOWN_REAL_FONTS:
        return False
    # Single short word (≤12 chars), no spaces, not a known font → likely brand font
    if " " not in low and len(low) <= 12 and low.isalpha():
        return True
    return False


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

    def _skip(family: str) -> bool:
        return not family or _is_icon_font(family)

    def _skip_for_body(family: str) -> bool:
        """Brand-custom fonts (Lays, Nike) are OK for headline but NOT body."""
        return _skip(family) or _is_brand_custom_font(family)

    # Pass 1: look for explicit usage tags
    for f in fonts:
        usage = (f.get("usage") or "").lower()
        family = f.get("family", "")
        if usage == "heading" and not headline_font and not _skip(family):
            headline_font = family
        elif usage == "body" and not body_font and not _skip_for_body(family):
            body_font = family

    # Pass 2: fallback to Google Fonts entries
    if not headline_font or not body_font:
        google_fonts = [
            f["family"] for f in fonts
            if f.get("source") == "google_fonts" and f.get("family")
            and not _skip(f["family"])
        ]
        if not headline_font and google_fonts:
            headline_font = google_fonts[0]
        if not body_font:
            for gf in google_fonts:
                if gf != headline_font and not _skip_for_body(gf):
                    body_font = gf
                    break

    # Pass 3: fallback to first available fonts
    if not headline_font or not body_font:
        all_families = [
            f["family"] for f in fonts
            if f.get("family") and not _skip(f["family"])
        ]
        if not headline_font and all_families:
            headline_font = all_families[0]
        if not body_font:
            for fam in all_families:
                if fam != headline_font and not _skip_for_body(fam):
                    body_font = fam
                    break

    return headline_font, body_font
