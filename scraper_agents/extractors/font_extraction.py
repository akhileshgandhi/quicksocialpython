"""
Pure font-extraction functions for the agentic scraper.

No AI calls, no state mutation — just deterministic extraction from
HTML ``<style>`` blocks, ``<link>`` tags, inline styles, and external CSS.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from scraper_agents.config import TIMEOUTS
from scraper_agents.extractors.html_helpers import make_absolute_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic / system fonts that should never appear in brand typography
# ---------------------------------------------------------------------------
_GENERIC_FONTS = {
    "sans-serif", "serif", "monospace", "cursive", "fantasy", "system-ui",
    "ui-sans-serif", "ui-serif", "ui-monospace", "ui-rounded",
    "-apple-system", "blinkmacsystemfont", "segoe ui", "arial",
    "helvetica", "helvetica neue", "times new roman", "times",
    "courier new", "courier", "verdana", "tahoma", "trebuchet ms",
    "georgia", "palatino", "garamond", "inherit", "initial", "unset",
    "glyphicons halflings", "fontawesome", "font awesome", "material icons",
    "material symbols", "icomoon", "ionicons", "feather", "bootstrap-icons",
}

# Language-specific font variant suffixes to strip
# "Open Sans Hebrew" → "Open Sans", "Noto Sans Bengali" → "Noto Sans"
_LANG_SUFFIX_RE = re.compile(
    r'\s+(?:Hebrew|Arabic|Bengali|Devanagari|Georgian|Gujarati|'
    r'Gurmukhi|Kannada|Khmer|Korean|Lao|Malayalam|Myanmar|'
    r'Oriya|Sinhala|Tamil|Telugu|Thai|Tibetan|Vietnamese|'
    r'SC|TC|JP|KR|HK)$', re.I,
)

# ---------------------------------------------------------------------------
# Shared regexes
# ---------------------------------------------------------------------------
# Match only font-family CSS variables (exclude --font-weight, --font-size, etc.)
_FONT_VAR_RE = re.compile(
    r'--font(?!-(?:weight|size|style|stretch|display|variant|feature|optical))'
    r'[-\w]*:\s*[\'"]?([^\'";\}\n]+)',
    re.I,
)
_HEADING_VAR_RE = re.compile(r'--font.*(head|title|display|hero)', re.I)
_BODY_VAR_RE = re.compile(r'--font.*(body|text|base|content|paragraph)', re.I)

_HEADING_FONT_RE = re.compile(
    r'(?:^|\})\s*([^{]*(?:h[1-6]|\.hero|\.heading|\.title|\.display)[^{]*)'
    r'\{[^}]*font-family:\s*([^;}\n]+)',
    re.I | re.MULTILINE,
)
_BODY_FONT_RE = re.compile(
    r'(?:^|\})\s*(?:body|html|\.content|\.main|\.page)[^{]*'
    r'\{[^}]*font-family:\s*([^;}\n]+)',
    re.I | re.MULTILINE,
)
_HEADING_COLOR_RE = re.compile(
    r'(?:^|\})\s*([^{]*(?:h[1-3]|\.hero|\.heading|\.title|\.display)[^{]*)'
    r'\{[^}]*?(?<![a-z-])color:\s*(#[0-9a-fA-F]{3,8})',
    re.I | re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

def extract_fonts_comprehensive(soup, base_url: str) -> Dict[str, Any]:
    """Multi-source font extraction from HTML/CSS.

    Inspects Google Fonts ``<link>`` tags, ``@font-face`` blocks, CSS
    variables, inline styles, and external stylesheets.

    Returns::

        {
            "fonts":              List[dict]  — each {family, weights, source, usage},
            "fonts_annotated":    str         — human-readable summary,
            "google_fonts_url":   str | None  — first Google Fonts URL found,
            "headline_text_color": str | None — most common heading colour,
        }
    """
    fonts: List[Dict[str, Any]] = []
    seen_families: Dict[str, int] = {}   # family_lower -> index in fonts
    google_fonts_url: Optional[str] = None
    headline_text_color: Optional[str] = None

    # ----- internal helper --------------------------------------------------
    def _add_font(
        family: str,
        weights: Optional[List[str]] = None,
        source: str = "css",
        usage: str = "unknown",
    ):
        family = family.strip().strip("'\"")
        # Strip CSS junk: !important, trailing quotes, semicolons
        family = re.sub(r'\s*!important\s*', '', family).strip().rstrip(';"\'')
        if not family or family.lower() in _GENERIC_FONTS or len(family) < 2:
            return
        # Reject unresolved CSS variables, numeric values, and CSS functions
        if family.startswith("var(") or family.startswith("calc("):
            return
        if re.match(r'^[\d.]+(%|px|em|rem|pt|vw|vh)?$', family):
            return
        # Reject placeholder/generic custom font names (Custom_Font_Heading, etc.)
        _lower = family.lower()
        if "custom_font" in _lower or "custom-font" in _lower:
            return
        # Reject icon fonts (not real typography)
        if any(kw in _lower for kw in ["icon", "glyph", "symbol", "awesome", "icomoon"]):
            return
        # Normalize language-specific variants: "Open Sans Hebrew" → "Open Sans"
        family = _LANG_SUFFIX_RE.sub('', family).strip()
        if not family:
            return
        key = family.lower()
        if key in seen_families:
            idx = seen_families[key]
            if weights:
                existing = set(fonts[idx].get("weights") or [])
                existing.update(weights)
                fonts[idx]["weights"] = sorted(existing)
            if usage != "unknown" and fonts[idx].get("usage") == "unknown":
                fonts[idx]["usage"] = usage
            return
        seen_families[key] = len(fonts)
        fonts.append({
            "family": family,
            "weights": sorted(set(weights)) if weights else [],
            "source": source,
            "usage": usage,
        })

    # ── 1. Google Fonts <link> tags ────────────────────────────────────
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if "fonts.googleapis.com" in href:
            google_fonts_url = href
            for match in re.finditer(r'family=([^&]+)', href):
                raw = match.group(1).replace('+', ' ')
                parts = raw.split(':')
                family_name = parts[0]
                weights: List[str] = []
                if len(parts) > 1:
                    for w in re.findall(r'(\d{3,4})', parts[1]):
                        weights.append(w)
                _add_font(family_name, weights, "google_fonts", "unknown")

    # ── 2. @font-face blocks in <style> tags ───────────────────────────
    for style_tag in soup.find_all("style"):
        css_text = style_tag.string or ""
        for match in re.finditer(
            r'@font-face\s*\{[^}]*?font-family:\s*[\'"]?([^\'";\}]+)',
            css_text,
            re.I,
        ):
            _add_font(match.group(1), source="custom_font_face")

    # ── 3. CSS variable fonts (--font-heading, --font-body, etc.) ──────
    for style_tag in soup.find_all("style"):
        css_text = style_tag.string or ""
        for match in _FONT_VAR_RE.finditer(css_text):
            var_line = match.group(0)
            family_raw = match.group(1).split(",")[0].strip().strip("'\"")
            usage = "unknown"
            if _HEADING_VAR_RE.search(var_line):
                usage = "heading"
            elif _BODY_VAR_RE.search(var_line):
                usage = "body"
            _add_font(family_raw, source="css_variable", usage=usage)

    # ── 4. font-family on key elements (body, h1-h6, .hero, etc.) ─────
    for style_tag in soup.find_all("style"):
        css_text = style_tag.string or ""
        for match in _HEADING_FONT_RE.finditer(css_text):
            family_raw = match.group(2).split(",")[0].strip().strip("'\"")
            _add_font(family_raw, source="css_rule", usage="heading")
        for match in _BODY_FONT_RE.finditer(css_text):
            family_raw = match.group(1).split(",")[0].strip().strip("'\"")
            _add_font(family_raw, source="css_rule", usage="body")

    # Inline style on body / h1 / h2
    for tag_name in ["body", "h1", "h2"]:
        for tag in soup.find_all(tag_name, style=True)[:2]:
            style_val = tag.get("style", "")
            ff_match = re.search(r'font-family:\s*([^;]+)', style_val, re.I)
            if ff_match:
                family_raw = ff_match.group(1).split(",")[0].strip().strip("'\"")
                usage = "heading" if tag_name in ("h1", "h2") else "body"
                _add_font(family_raw, source="inline_style", usage=usage)

    # ── 5. Headline text colour ────────────────────────────────────────
    color_candidates: Dict[str, int] = {}
    for style_tag in soup.find_all("style"):
        css_text = style_tag.string or ""
        for match in _HEADING_COLOR_RE.finditer(css_text):
            hex_color = match.group(2).strip()
            h = hex_color.lstrip('#')
            if len(h) == 3:
                h = ''.join(c * 2 for c in h)
                hex_color = f"#{h}"
            if len(h) != 6:
                continue
            try:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                if r > 240 and g > 240 and b > 240:
                    continue
            except ValueError:
                continue
            color_candidates[hex_color.upper()] = color_candidates.get(hex_color.upper(), 0) + 1
    if color_candidates:
        headline_text_color = max(color_candidates, key=color_candidates.get)

    # ── 6. External CSS files (same-origin, first 3) ───────────────────
    try:
        ext_css_count = 0
        for link in soup.find_all("link", rel="stylesheet", href=True):
            if ext_css_count >= 3:
                break
            css_url = make_absolute_url(link["href"], base_url)
            parsed_css = urlparse(css_url)
            parsed_base = urlparse(base_url)
            if parsed_css.netloc and parsed_css.netloc != parsed_base.netloc:
                continue
            try:
                css_resp = requests.get(
                    css_url,
                    timeout=TIMEOUTS["css_fetch"],
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                if css_resp.status_code == 200:
                    ext_css = css_resp.text[:50000]
                    # @font-face in external CSS
                    for match in re.finditer(
                        r'@font-face\s*\{[^}]*?font-family:\s*[\'"]?([^\'";\}]+)',
                        ext_css,
                        re.I,
                    ):
                        _add_font(match.group(1), source="external_css")
                    # CSS variable fonts
                    for match in _FONT_VAR_RE.finditer(ext_css):
                        var_line = match.group(0)
                        family_raw = match.group(1).split(",")[0].strip().strip("'\"")
                        usage = "unknown"
                        if _HEADING_VAR_RE.search(var_line):
                            usage = "heading"
                        elif _BODY_VAR_RE.search(var_line):
                            usage = "body"
                        _add_font(family_raw, source="external_css_variable", usage=usage)
                    # Heading font-family
                    for match in _HEADING_FONT_RE.finditer(ext_css):
                        family_raw = match.group(2).split(",")[0].strip().strip("'\"")
                        _add_font(family_raw, source="external_css", usage="heading")
                    for match in _BODY_FONT_RE.finditer(ext_css):
                        family_raw = match.group(1).split(",")[0].strip().strip("'\"")
                        _add_font(family_raw, source="external_css", usage="body")
                    # Heading colour in external CSS
                    if not headline_text_color:
                        for match in _HEADING_COLOR_RE.finditer(ext_css):
                            hex_color = match.group(2).strip()
                            h = hex_color.lstrip('#')
                            if len(h) == 3:
                                h = ''.join(c * 2 for c in h)
                                hex_color = f"#{h}"
                            if len(h) != 6:
                                continue
                            try:
                                rv, gv, bv = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                                if rv > 240 and gv > 240 and bv > 240:
                                    continue
                            except ValueError:
                                continue
                            color_candidates[hex_color.upper()] = color_candidates.get(hex_color.upper(), 0) + 1
                    ext_css_count += 1
            except Exception:
                pass
        # Re-evaluate headline colour after external CSS
        if color_candidates and not headline_text_color:
            headline_text_color = max(color_candidates, key=color_candidates.get)
    except Exception:
        pass

    # ── Build annotated string ─────────────────────────────────────────
    annotations: List[str] = []
    for f in fonts:
        parts = [f["family"]]
        if f.get("source") and f["source"] != "css":
            parts.append(f["source"].replace("_", " "))
        if f.get("usage") and f["usage"] != "unknown":
            parts.append(f["usage"])
        if f.get("weights"):
            parts.append("/".join(f["weights"]))
        annotations.append(
            f"{f['family']} ({', '.join(parts[1:])})" if len(parts) > 1 else f["family"]
        )

    return {
        "fonts": fonts,
        "fonts_annotated": ", ".join(annotations) if annotations else "No fonts found",
        "google_fonts_url": google_fonts_url,
        "headline_text_color": headline_text_color,
    }
