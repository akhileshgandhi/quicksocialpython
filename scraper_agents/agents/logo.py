"""
LogoAgent — finds, downloads, validates, and saves the company logo.

Waterfall strategy (stops on first success):
  A. OG image (if filename contains "logo") + stale Next.js OG refresh (A2)
  A3. Playwright inline SVG inside header/nav home link (when enabled)
  A. JSON-LD Organization logo (ambiguous small squares keep fallback, try HTML next)
  B. High-confidence HTML candidates (priority selectors, scored/ranked)
  D. Playwright rendered DOM
  E. Gemini web search for logo URL
  F. Wikipedia pageimages API
  G. Public APIs (Clearbit, DuckDuckGo favicon, Google favicon)
  H. Favicon / apple-touch-icon
  I. Common URL path probing
  J. Low-confidence HTML candidates (positive scores only)
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

import requests
from bs4 import BeautifulSoup
from PIL import Image

from scraper_agents.agents.base import BaseAgent
from gemini_fallback import aio_generate_content_with_fallback
from scraper_agents.state import ScrapeState
from scraper_agents.config import (
    TIMEOUTS,
    LOGO_SCORE,
    DEFAULT_HEADERS,
    LOGO_CONFIG,
    THEME_CDN_DOMAINS,
)
from scraper_agents.extractors.html_helpers import (
    make_absolute_url,
    extract_jsonld_logo,
    is_home_like_href,
)
from scraper_agents.extractors.image_helpers import (
    score_logo_candidate,
    rank_logo_candidates,
    validate_logo_image,
    convert_svg_to_png,
    is_icon_image,
)
from scraper_agents.prompts.logo_search import LOGO_SEARCH_PROMPT

logger = logging.getLogger(__name__)

# URL paths to probe as a last-resort logo discovery strategy
_PROBE_PATHS = [
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/logo.svg",
    "/logo.png",
    "/favicon.svg",
    "/images/logo.svg",
    "/images/logo.png",
    "/img/logo.svg",
    "/img/logo.png",
    "/assets/logo.svg",
    "/assets/logo.png",
    "/static/logo.svg",
    "/static/logo.png",
    "/assets/images/logo.svg",
    "/assets/images/logo.png",
    "/public/logo.svg",
    "/public/logo.png",
    "/media/logo.svg",
    "/media/logo.png",
]

LOW_CONFIDENCE_THRESHOLD = LOGO_SCORE.get("high_confidence_threshold", 10)


def _trusted_logo_cdn_hosts() -> set[str]:
    """Hosts that may serve first-party logos (JSON-LD / OG may point here)."""
    raw = LOGO_CONFIG.get("trusted_logo_cdn_hosts", frozenset())
    hosts = {h.lower().lstrip("www.") for h in raw}
    for d in THEME_CDN_DOMAINS:
        if isinstance(d, str):
            hosts.add(d.lower().lstrip("www."))
    return hosts


def structured_logo_url_trusted(logo_url: str, base_url: str) -> bool:
    """True if *logo_url* is same-site or on a known first-party CDN for *base_url*."""
    lu = urlparse(logo_url)
    bu = urlparse(base_url)
    if not bu.netloc:
        return True
    if not lu.netloc:
        return True
    lh = lu.netloc.lower().split(":")[0].lstrip("www.")
    bh = bu.netloc.lower().split(":")[0].lstrip("www.")
    if lh == bh:
        return True
    if lh.endswith("." + bh):
        return True
    if lh in _trusted_logo_cdn_hosts():
        return True
    # Vercel Blob URLs used in JSON-LD Organization.logo (subdomain.public.blob.vercel-storage.com)
    for suf in ("public.blob.vercel-storage.com", "blob.vercel-storage.com"):
        if lh == suf or lh.endswith("." + suf):
            return True
    return False


def _is_nextjs_numbered_media_image(url: str) -> bool:
    """True for ``.../static/media/image 2.*`` / ``image%202`` (carousel art, not navbar mark)."""
    dec = unquote(url.lower())
    if "main_logo" in dec:
        return False
    return bool(re.search(r"static/media/image[\s.%20_-]*\d+", dec))


# Playwright: collect logo-like asset URLs from the *rendered* page (A2 refresh + optional D extras).
# includeMeta: when False, skip og/twitter (e.g. second pass after hover — avoid duplicate meta).
_PLAYWRIGHT_LOGO_URLS_JS = r"""
(includeMeta) => {
  const out = [];
  const seen = new Set();
  const push = (u) => {
    if (!u || u.startsWith('data:') || seen.has(u)) return;
    seen.add(u);
    out.push(u);
  };
  const parseBg = (bg) => {
    if (!bg || bg === 'none') return;
    const i = bg.indexOf('url(');
    if (i < 0) return;
    let rest = bg.slice(i + 4).trim();
    let u = '';
    if (rest[0] === '"' || rest[0] === "'") {
      const q = rest[0];
      const end = rest.indexOf(q, 1);
      if (end > 0) u = rest.slice(1, end);
    } else {
      const end = rest.indexOf(')');
      if (end > 0) u = rest.slice(0, end).trim();
    }
    if (u && !u.startsWith('data:')) push(u);
  };
  try {
    document.querySelectorAll(
      '.main_logo, .navbar-brand, .site-logo, #logo, a.navbar-brand, .brand-mark'
    ).forEach((el) => {
      try { parseBg(getComputedStyle(el).backgroundImage); } catch (e) {}
    });
  } catch (e) {}
  if (includeMeta) {
    try {
      document.querySelectorAll(
        'meta[property="og:image"], meta[name="twitter:image"], meta[name="twitter:image:src"]'
      ).forEach((m) => {
        const c = m.getAttribute('content');
        if (c) push(c.trim());
      });
    } catch (e) {}
  }
  try {
    document.querySelectorAll(
      'nav img, header img, .navbar-brand img, a.navbar-brand img'
    ).forEach((img) => {
      try {
        if (img.currentSrc) push(img.currentSrc);
        else if (img.src) push(img.src);
        const ss = img.getAttribute('srcset');
        if (ss) {
          const first = ss.split(',')[0].trim().split(/\s+/)[0];
          if (first) push(first);
        }
      } catch (e) {}
    });
  } catch (e) {}
  return out;
}
"""

# Video / <picture> in header only (optional second evaluate — keeps meta separate from media)
_PLAYWRIGHT_HEADER_MEDIA_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const push = (u) => {
    if (!u || u.startsWith('data:') || seen.has(u)) return;
    seen.add(u);
    out.push(u);
  };
  try {
    document.querySelectorAll(
      'header video[poster], nav video[poster], .navbar-brand video[poster]'
    ).forEach((v) => {
      try {
        const p = v.getAttribute('poster');
        if (p) push(p.trim());
      } catch (e) {}
    });
  } catch (e) {}
  try {
    document.querySelectorAll('header picture source, nav picture source').forEach((s) => {
      try {
        const ss = s.getAttribute('srcset');
        const sr = s.getAttribute('src');
        if (ss) {
          const first = ss.split(',')[0].trim().split(/\s+/)[0];
          if (first) push(first);
        } else if (sr) push(sr.trim());
      } catch (e) {}
    });
  } catch (e) {}
  return out;
}
"""

# Best-scoring inline SVG inside a canonical home <a> in header/nav (SVG-first sites).
_PLAYWRIGHT_HOME_SVG_JS = r"""
() => {
  function isHomeHref(href) {
    if (!href) return false;
    const h = href.trim();
    if (h === '/' || h === '#' || h === '') return true;
    try {
      const u = new URL(h, window.location.origin);
      let path = u.pathname.replace(/\/+$/, '') || '/';
      if (path === '/') return true;
      if (/^\/[a-z]{2}(-[a-z]{2})?(\.html?)?$/i.test(path)) return true;
    } catch (e) {}
    return false;
  }
  function scoreSvg(svg) {
    const vb = svg.getAttribute('viewBox') || '';
    if (vb) {
      const p = vb.trim().split(/[\s,]+/);
      if (p.length >= 4) {
        const vw = parseFloat(p[2]), vh = parseFloat(p[3]);
        if (!isNaN(vw) && !isNaN(vh) && vw > 0 && vh > 0) return vw * vh;
      }
    }
    const w = parseFloat(svg.getAttribute('width')) || 0;
    const h = parseFloat(svg.getAttribute('height')) || 0;
    if (w > 0 && h > 0) return w * h;
    return (svg.outerHTML || '').length;
  }
  let best = null;
  let bestScore = -1;
  const roots = [...document.querySelectorAll('header, nav, [role="banner"]')];
  for (const root of roots) {
    const links = root.querySelectorAll('a[href]');
    for (const a of links) {
      if (!isHomeHref(a.getAttribute('href'))) continue;
      const svgs = a.querySelectorAll('svg');
      for (const svg of svgs) {
        const html = svg.outerHTML;
        if (html.length < 200) continue;
        const vb = svg.getAttribute('viewBox') || '';
        if (vb) {
          const p = vb.trim().split(/[\s,]+/);
          if (p.length >= 4) {
            const vw = parseFloat(p[2]), vh = parseFloat(p[3]);
            if (!isNaN(vw) && !isNaN(vh) && vw <= 20 && vh <= 20) continue;
          }
        }
        const sc = scoreSvg(svg);
        if (sc > bestScore) {
          bestScore = sc;
          best = html;
        }
      }
    }
  }
  return best;
}
"""


class LogoAgent(BaseAgent):
    """Find, download, validate, and save the company logo."""

    agent_name = "logo"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    async def run(self, state: ScrapeState) -> None:
        try:
            await self._run_waterfall(state)
        finally:
            # Always signal that logo work is done (success or failure)
            state.logo_ready.set()

    # ------------------------------------------------------------------
    # Waterfall
    # ------------------------------------------------------------------
    async def _run_waterfall(self, state: ScrapeState) -> None:
        if not state.download_logo:
            self.log("download_logo=False, skipping")
            return

        company_name = (
            state.company_name
            or state.company_name_hint
            or state.domain
            or "company"
        )
        company_slug = re.sub(r"[^a-z0-9]", "", company_name.lower())
        base_url = state.base_url or state.website_url

        # Pre-extract some data sources
        jsonld_logo_url = extract_jsonld_logo(state.structured_data)
        og_logo_url = self._extract_og_logo(state.og_data)

        # Build scored HTML candidates
        real_images = [
            img for img in state.images
            if img.get("src") != "__inline_svg__"
        ]
        scored_candidates = rank_logo_candidates(
            real_images, base_url, company_slug=company_slug
        )
        best_html_score = scored_candidates[0][0] if scored_candidates else -999

        # Deduplicate
        seen: set = set()
        deduped: List[Tuple[int, str]] = []
        for s, c in scored_candidates:
            if c not in seen:
                seen.add(c)
                deduped.append((s, c))
        scored_candidates = deduped

        self.log(
            f"HTML candidates: {len(scored_candidates)}, best_score={best_html_score}, "
            f"OG={og_logo_url or 'none'}, JSON-LD={jsonld_logo_url or 'none'}, "
            f"favicon={state.favicon_url or 'none'}"
        )
        for i, (sc, url) in enumerate(scored_candidates[:5]):
            short = url.rsplit("/", 1)[-1][:60] if "/" in url else url[:60]
            self.log(f"  #{i+1}: score={sc:+d}  {short}")

        # ── Strategy A: Authoritative sources (OG → JSON-LD) ────────
        # Sites declare their logo in structured data / OG — try these first.
        # OG image is often more current than JSON-LD (companies update it more).
        # However, if the downloaded image is tiny (<100px), it's likely a
        # favicon/android-icon — save as fallback but keep trying HTML candidates.
        _jsonld_fallback = False

        if og_logo_url and not self.should_stop():
            if not structured_logo_url_trusted(og_logo_url, base_url):
                self.log(
                    f"[A] OG logo host does not match site — skipping: {og_logo_url}",
                    level="warning",
                )
            else:
                self.log(f"[A] OG image logo: {og_logo_url}")
                result = await self._try_download(
                    og_logo_url,
                    state,
                    company_name,
                    relaxed_structured_data=True,
                )
                if result:
                    # Check if it's tiny — if so, save as fallback
                    if self._is_tiny_logo(state):
                        self.log("[A] OG logo is tiny — saving as fallback, trying HTML next")
                        _jsonld_fallback = True
                    else:
                        return
                elif (
                    self._last_download_reason
                    and "404" in self._last_download_reason
                    and "/_next/" in og_logo_url.lower()
                ):
                    # Static HTML often lists a stale hashed ``/_next/static/media/`` URL;
                    # the live page has the current hash (OG 404 → wrong HTML candidate wins).
                    self.log(
                        "[A2] Next.js OG URL returned 404 — fetching live og:image / header",
                        level="warning",
                    )
                    if await self._try_playwright_fresh_logo_after_stale_next_og(
                        state, base_url, company_name, stale_og_url=og_logo_url
                    ):
                        if self._is_tiny_logo(state):
                            self.log("[A2] Live logo is tiny — saving as fallback, trying HTML next")
                            _jsonld_fallback = True
                        else:
                            return

        # ── Strategy A3: Playwright — inline SVG in home link (after OG, before JSON-LD) ──
        if LOGO_CONFIG.get("logo_svg_home_capture", True) and not self.should_stop():
            self.log("[A3] Playwright home-link inline SVG")
            if await self._try_playwright_home_svg(state, company_name):
                return

        # JSON-LD: site literally declares "this is my logo" in machine-readable
        # structured data. Reliable but sometimes stale.
        if jsonld_logo_url and not _jsonld_fallback and not self.should_stop():
            if not structured_logo_url_trusted(jsonld_logo_url, base_url):
                self.log(
                    f"[A] JSON-LD logo host does not match site — skipping: {jsonld_logo_url}",
                    level="warning",
                )
            else:
                self.log(f"[A] JSON-LD logo: {jsonld_logo_url}")
                result = await self._try_download(
                    jsonld_logo_url,
                    state,
                    company_name,
                    relaxed_structured_data=True,
                )
                if result:
                    if self._is_tiny_logo(state):
                        self.log("[A] JSON-LD logo is tiny — saving as fallback, trying HTML next")
                        _jsonld_fallback = True
                    elif self._is_ambiguous_square_logo(state):
                        self.log(
                            "[A] JSON-LD logo is small square — may be icon not lockup; "
                            "keeping as fallback, trying HTML next"
                        )
                        _jsonld_fallback = True
                    else:
                        return

        # ── Strategy B: High-confidence HTML candidates ───────────────
        # Scored & ranked — tried when authoritative sources fail OR were tiny.
        if best_html_score > LOW_CONFIDENCE_THRESHOLD and not self.should_stop():
            self.log(f"[B] High-confidence HTML (threshold={LOW_CONFIDENCE_THRESHOLD})")
            for score_val, candidate_url in scored_candidates[:8]:
                if self.should_stop():
                    break
                if score_val <= LOW_CONFIDENCE_THRESHOLD:
                    break
                result = await self._try_download(candidate_url, state, company_name)
                if result:
                    return

        # If we had a tiny JSON-LD/OG fallback and HTML didn't find anything
        # better, the fallback is already saved in state — accept it.
        if _jsonld_fallback and state.logo_url:
            self.log(f"[A] Accepting tiny fallback logo: {state.logo_url}")
            return

        # ── Strategy D: Playwright rendered DOM ───────────────────────
        if not self.should_stop():
            self.log("[D] Playwright rendered DOM")
            pw_found = await self._try_playwright(
                state, base_url, company_slug, company_name
            )
            if pw_found:
                return

        # ── Strategy E: Gemini web search for logo URL ────────────────
        if not self.should_stop():
            expand = LOGO_CONFIG.get("expand_gemini_fallback", True)
            need_gemini = (
                not scored_candidates
                or (expand and not state.logo_url)
            )
            if need_gemini:
                self.log("[E] Gemini web search")
                ws_found = await self._try_web_search(state, company_name, base_url)
                if ws_found:
                    return

        # ── Strategy F: Wikipedia pageimages API ──────────────────────
        if not self.should_stop():
            self.log("[F] Wikipedia pageimages API")
            wiki_found = await self._try_wikipedia(state, company_name)
            if wiki_found:
                return

        # ── Strategy G: Public APIs ───────────────────────────────────
        if not self.should_stop():
            self.log("[G] Public logo APIs")
            api_found = await self._try_public_apis(state, company_name)
            if api_found:
                return

        # ── Strategy H: Favicon fallback ──────────────────────────────
        if state.favicon_url and not self.should_stop():
            self.log(f"[H] Favicon: {state.favicon_url}")
            result = await self._try_download(state.favicon_url, state, company_name)
            if result:
                return

        # ── Strategy I: URL path probing ──────────────────────────────
        if not self.should_stop():
            self.log("[I] URL path probing")
            probe_found = await self._try_path_probing(state, company_name, base_url)
            if probe_found:
                return

        # ── Strategy J: Low-confidence HTML candidates ────────────────
        if scored_candidates and not self.should_stop():
            self.log("[J] Low-confidence HTML fallback")
            for score_val, candidate_url in scored_candidates[:8]:
                if self.should_stop():
                    break
                if score_val <= 0:
                    break
                if candidate_url == state.favicon_url:
                    continue  # already tried
                result = await self._try_download(candidate_url, state, company_name)
                if result:
                    return

        self.log("No valid logo found after all strategies", level="warning")

    # ------------------------------------------------------------------
    # Tiny logo check
    # ------------------------------------------------------------------
    @staticmethod
    def _is_tiny_logo(state: ScrapeState, threshold: int = 100) -> bool:
        """Return True if the currently saved logo is smaller than threshold px."""
        if not state.logo_bytes:
            return False
        try:
            img = Image.open(BytesIO(state.logo_bytes))
            w, h = img.size
            return w < threshold and h < threshold
        except Exception:
            return False

    @staticmethod
    def _is_ambiguous_square_logo(state: ScrapeState) -> bool:
        """True for ~square app icons (e.g. 128x128) that JSON-LD may mislabel as logo."""
        if not state.logo_bytes:
            return False
        try:
            img = Image.open(BytesIO(state.logo_bytes))
            w, h = img.size
            if w < 80 or h < 80 or w > 220 or h > 220:
                return False
            aspect = w / max(h, 1)
            return 0.88 <= aspect <= 1.12
        except Exception:
            return False

    # ------------------------------------------------------------------
    # OG image extraction
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_og_logo(og_data: Dict[str, str]) -> Optional[str]:
        """Return og:image URL only if the filename contains 'logo'."""
        for key in ("image", "image:url"):
            url = og_data.get(key, "")
            if url:
                filename = url.rsplit("/", 1)[-1].lower() if "/" in url else url.lower()
                if "logo" in filename:
                    return url
        return None

    @staticmethod
    def _rank_fresh_logo_urls(
        raw_urls: List[str],
        base_url: str,
        stale_url: str,
    ) -> List[str]:
        """Prefer main_logo / *logo* over Next.js ``media/image N`` carousel assets."""
        ranked: List[Tuple[int, str]] = []
        stale_norm = (stale_url or "").rstrip("/").lower()
        for u in raw_urls:
            if not u or not str(u).strip():
                continue
            u = str(u).strip()
            if u.startswith("data:"):
                continue
            absu = make_absolute_url(u, base_url)
            if absu.rstrip("/").lower() == stale_norm:
                continue
            if not structured_logo_url_trusted(absu, base_url):
                continue
            dec = unquote(absu.lower())
            fn = absu.rsplit("/", 1)[-1].lower()
            tier = 3
            if "main_logo" in dec:
                tier = 0
            elif _is_nextjs_numbered_media_image(absu):
                tier = 6
            elif "logo" in fn or "logo" in dec:
                tier = 1
            ranked.append((tier, absu))
        ranked.sort(key=lambda x: (x[0], len(x[1]), x[1]))
        out: List[str] = []
        seen: set = set()
        for _, u in ranked:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out

    async def _try_playwright_fresh_logo_after_stale_next_og(
        self,
        state: ScrapeState,
        base_url: str,
        company_name: str,
        stale_og_url: str,
    ) -> bool:
        """Re-read live ``og:image`` / header ``img`` when ``/_next/static/media/`` URL 404s.

        Crawler HTML can reference a hashed filename from an older deploy; the live
        page's meta and ``img`` tags point at the current asset (see also
        ``chennai_logs.txt`` / legacy ``scraper.py`` OG vs JSON-LD notes).
        """
        try:
            from playwright.sync_api import sync_playwright as _sp  # noqa: F401
        except ImportError:
            self.log("Playwright not installed — cannot refresh stale Next OG", level="warning")
            return False

        def _collect() -> List[str]:
            from playwright.sync_api import sync_playwright as _sp2

            pw = _sp2().start()
            urls: List[str] = []
            try:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
                page.goto(
                    state.website_url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUTS["page_load_ms"],
                )
                extra_ms = int(LOGO_CONFIG.get("playwright_extra_wait_ms", 0) or 0)
                if LOGO_CONFIG.get("playwright_aggressive_render"):
                    extra_ms = max(extra_ms, 2000)
                page.wait_for_timeout(TIMEOUTS["page_render_wait_ms"] + extra_ms)

                def _merge_eval_result(raw: object) -> None:
                    for x in raw or []:
                        s = str(x).strip()
                        if s and s not in urls:
                            urls.append(s)

                try:
                    _merge_eval_result(page.evaluate(_PLAYWRIGHT_LOGO_URLS_JS, True))
                except Exception as e:
                    logger.warning("[A2] logo URL evaluate failed: %s", e)

                if LOGO_CONFIG.get("playwright_header_media_extras", True):
                    try:
                        _merge_eval_result(page.evaluate(_PLAYWRIGHT_HEADER_MEDIA_JS))
                    except Exception as e:
                        logger.warning("[A2] header media evaluate failed: %s", e)

                if LOGO_CONFIG.get("playwright_hover_logo_probe", False):
                    try:
                        hover_ms = int(LOGO_CONFIG.get("playwright_hover_settle_ms", 500) or 500)
                        for sel in (
                            "header a.navbar-brand",
                            "nav a.navbar-brand",
                            "a.navbar-brand",
                            "header .main_logo",
                            ".navbar-brand",
                        ):
                            try:
                                loc = page.locator(sel)
                                if loc.count() == 0:
                                    continue
                                loc.first.hover(timeout=3500)
                                page.wait_for_timeout(hover_ms)
                                break
                            except Exception:
                                continue
                        try:
                            _merge_eval_result(page.evaluate(_PLAYWRIGHT_LOGO_URLS_JS, False))
                        except Exception as e:
                            logger.warning("[A2] post-hover evaluate failed: %s", e)
                        if LOGO_CONFIG.get("playwright_header_media_extras", True):
                            try:
                                _merge_eval_result(page.evaluate(_PLAYWRIGHT_HEADER_MEDIA_JS))
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug("[A2] hover probe skipped: %s", e)

                browser.close()
            finally:
                pw.stop()
            return urls

        try:
            raw_urls = await asyncio.to_thread(_collect)
        except Exception as e:
            self.log(f"[A2] Playwright refresh failed: {e}", level="warning")
            return False

        candidates = self._rank_fresh_logo_urls(raw_urls, base_url, stale_og_url)
        if not candidates:
            self.log("[A2] No alternative logo URLs from live DOM", level="warning")
            return False

        # Prefer real navbar / CSS assets; try ``media/image N`` only after (carousel junk).
        primary = [u for u in candidates if not _is_nextjs_numbered_media_image(u)]
        fallback = [u for u in candidates if _is_nextjs_numbered_media_image(u)]
        ordered = primary + fallback

        self.log(
            f"[A2] Trying {len(ordered)} live URL(s) after Next OG 404 "
            f"({len(primary)} non-carousel first)"
        )
        for cand in ordered[:36]:
            if self.should_stop():
                break
            if await self._try_download(
                cand,
                state,
                company_name,
                relaxed_structured_data=True,
            ):
                return True
        return False

    async def _try_playwright_home_svg(
        self,
        state: ScrapeState,
        company_name: str,
    ) -> bool:
        """Render page; take first SVG inside header/nav home <a>; convert via data URI."""
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            self.log("[A3] Playwright not installed — skip home SVG", level="warning")
            return False

        def _collect() -> Optional[str]:
            from playwright.sync_api import sync_playwright as _sp

            pw = _sp().start()
            try:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
                page.goto(
                    state.website_url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUTS["page_load_ms"],
                )
                extra_ms = int(LOGO_CONFIG.get("playwright_extra_wait_ms", 0) or 0)
                svg_extra = int(LOGO_CONFIG.get("logo_svg_home_extra_wait_ms", 0) or 0)
                page.wait_for_timeout(
                    TIMEOUTS["page_render_wait_ms"] + extra_ms + svg_extra
                )
                svg_html = page.evaluate(_PLAYWRIGHT_HOME_SVG_JS)
                browser.close()
                if svg_html and len(str(svg_html)) >= 200:
                    return str(svg_html)
                return None
            finally:
                pw.stop()

        try:
            svg_html = await asyncio.to_thread(_collect)
        except Exception as e:
            self.log(f"[A3] Home SVG Playwright failed: {e}", level="warning")
            return False

        if not svg_html:
            self.log("[A3] No inline SVG in home link")
            return False

        svg_b64 = base64.b64encode(svg_html.encode("utf-8")).decode("ascii")
        data_uri = f"data:image/svg+xml;base64,{svg_b64}"
        self.log(f"[A3] Home-link SVG captured ({len(svg_html)} chars)")
        return await self._try_download(data_uri, state, company_name)

    # ------------------------------------------------------------------
    # Download, validate, save
    # ------------------------------------------------------------------
    async def _try_download(
        self,
        logo_url: str,
        state: ScrapeState,
        company_name: str,
        timeout: Optional[int] = None,
        *,
        relaxed_structured_data: bool = False,
    ) -> bool:
        """Download *logo_url*, validate, save. Returns True on success."""
        self._last_download_reason = None
        dl_result = await asyncio.to_thread(
            self._download_logo,
            logo_url,
            state.scrape_id,
            company_name,
            timeout or TIMEOUTS["logo_download"],
            relaxed_structured_data,
        )
        if dl_result.get("success"):
            state.logo_url = dl_result.get("original_url") or dl_result.get("url")
            state.logo_local_path = dl_result.get("local_path")
            state.logo_cloudinary_url = dl_result.get("cloudinary_url")
            state.logo_bytes = dl_result.get("logo_bytes")
            self.log(f"Logo saved: {state.logo_url}")
            return True
        else:
            self._last_download_reason = str(dl_result.get("reason", "unknown"))
            self.log(f"Rejected: {dl_result.get('reason', 'unknown')}")
            return False

    def _download_logo(
        self,
        logo_url: str,
        scrape_id: str,
        company_name: str,
        timeout: int = 15,
        relaxed_structured_data: bool = False,
    ) -> Dict[str, Any]:
        """Download, validate, and save logo. Runs in a thread."""
        try:
            if not logo_url:
                return {"success": False, "reason": "No logo URL"}

            # ── Handle base64 SVG data URIs ───────────────────────────
            if logo_url.startswith("data:image/svg+xml"):
                return self._handle_data_uri_svg(logo_url, scrape_id, company_name)

            # ── Handle other data URIs ────────────────────────────────
            if logo_url.startswith("data:"):
                return {"success": False, "reason": "Non-SVG data URI not supported"}

            logger.info(f"[LOGO] Downloading: {logo_url}")
            response = requests.get(
                logo_url,
                headers=DEFAULT_HEADERS,
                timeout=timeout,
                allow_redirects=True,
            )
            if response.status_code != 200:
                return {"success": False, "reason": f"HTTP {response.status_code}"}

            content_bytes = response.content
            content_type = response.headers.get("content-type", "")

            # ── SVG handling ──────────────────────────────────────────
            if "svg" in content_type or logo_url.lower().endswith(".svg"):
                svg_text = content_bytes[:500].decode("utf-8", errors="ignore").lower()
                if "<svg" not in svg_text and "<?xml" not in svg_text:
                    return {"success": False, "reason": "Invalid SVG content"}
                if len(content_bytes) < 300:
                    return {"success": False, "reason": f"SVG too small ({len(content_bytes)}B) — likely a UI icon"}
                logger.info("[LOGO] SVG detected - converting to PNG")
                png_bytes = convert_svg_to_png(content_bytes)
                if png_bytes:
                    content_bytes = png_bytes
                else:
                    return {"success": False, "reason": "SVG->PNG conversion failed"}

            # ── Validate ──────────────────────────────────────────────
            validation = validate_logo_image(
                content_bytes,
                relaxed_structured_data=relaxed_structured_data,
            )
            if not validation["valid"]:
                return {"success": False, "reason": f"Validation failed: {validation['reason']}"}
            logger.info(f"[LOGO] Validated: {validation.get('width', '?')}x{validation.get('height', '?')}px")
            if validation.get("resized_bytes"):
                content_bytes = validation["resized_bytes"]

            # ── Save to disk ──────────────────────────────────────────
            save_result = self._save_logo(content_bytes, scrape_id, company_name, logo_url)
            return save_result

        except Exception as e:
            logger.error(f"[LOGO] Download failed: {e}")
            return {"success": False, "reason": str(e)}

    def _handle_data_uri_svg(
        self, logo_url: str, scrape_id: str, company_name: str
    ) -> Dict[str, Any]:
        """Decode a data:image/svg+xml URI, convert to PNG, validate, save."""
        try:
            if ";base64," in logo_url:
                b64_data = logo_url.split(";base64,", 1)[1]
                svg_bytes = base64.b64decode(b64_data)
            else:
                svg_text = unquote(logo_url.split(",", 1)[1])
                svg_bytes = svg_text.encode("utf-8")

            svg_preview = svg_bytes[:300].decode("utf-8", errors="ignore").lower()
            if "<svg" not in svg_preview and "<?xml" not in svg_preview:
                return {"success": False, "reason": "Data URI doesn't contain valid SVG"}

            if len(svg_bytes) < 300:
                return {"success": False, "reason": f"SVG too small ({len(svg_bytes)}B) — likely a UI icon"}

            png_bytes = convert_svg_to_png(svg_bytes)
            if not png_bytes:
                return {"success": False, "reason": "SVG->PNG conversion failed"}

            validation = validate_logo_image(png_bytes)
            if not validation["valid"]:
                return {"success": False, "reason": f"Validation failed: {validation['reason']}"}
            if validation.get("resized_bytes"):
                png_bytes = validation["resized_bytes"]

            return self._save_logo(png_bytes, scrape_id, company_name, original_url=None)
        except Exception as e:
            return {"success": False, "reason": f"Data URI decode failed: {e}"}

    def _save_logo(
        self,
        content_bytes: bytes,
        scrape_id: str,
        company_name: str,
        original_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save logo bytes to disk and optionally upload to Cloudinary."""
        sanitized = re.sub(r"[^\w\s-]", "", company_name.lower())
        sanitized = re.sub(r"[-\s]+", "_", sanitized)[:30]
        scrape_folder = f"{scrape_id[:8]}_{sanitized}"

        organized_path = self.storage_dir / "smart_scrape" / scrape_folder
        organized_path.mkdir(parents=True, exist_ok=True)

        logo_path = organized_path / "logo.png"
        with open(logo_path, "wb") as f:
            f.write(content_bytes)
        logger.info(f"[LOGO] Saved: {logo_path}")

        cloudinary_url = self._upload_to_cloudinary(
            content_bytes,
            folder=f"quicksocial/logos/{scrape_folder}",
            public_id="logo",
        )

        return {
            "success": True,
            "local_path": str(logo_path),
            "url": f"/images/smart_scrape/{scrape_folder}/logo.png",
            "original_url": original_url,
            "cloudinary_url": cloudinary_url,
            "logo_bytes": content_bytes,
        }

    @staticmethod
    def _upload_to_cloudinary(
        image_bytes: bytes, folder: str, public_id: str
    ) -> Optional[str]:
        """Upload to Cloudinary CDN. Returns secure_url or None."""
        try:
            import cloudinary
            import cloudinary.uploader

            cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
            api_key = os.environ.get("CLOUDINARY_API_KEY")
            api_secret = os.environ.get("CLOUDINARY_API_SECRET")
            if not all([cloud_name, api_key, api_secret]):
                return None

            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True,
            )
            result = cloudinary.uploader.upload(
                BytesIO(image_bytes),
                folder=folder,
                public_id=public_id,
                overwrite=True,
                resource_type="image",
            )
            url = result.get("secure_url")
            logger.info(f"[CLOUDINARY] Uploaded logo: {url}")
            return url
        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"[CLOUDINARY] Upload failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Strategy D: Playwright rendered DOM
    # ------------------------------------------------------------------
    async def _try_playwright(
        self,
        state: ScrapeState,
        base_url: str,
        company_slug: str,
        company_name: str,
    ) -> bool:
        """Launch Playwright to render JS-heavy pages, extract logo candidates."""
        try:
            from playwright.sync_api import sync_playwright  # noqa: F401
        except ImportError:
            self.log("Playwright not installed, skipping")
            return False

        def _render_page() -> Tuple[str, List[Dict[str, Any]]]:
            from playwright.sync_api import sync_playwright as _sp

            extra_candidates: List[Dict[str, Any]] = []
            pw = _sp().start()
            try:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(user_agent=DEFAULT_HEADERS["User-Agent"])
                aggressive = LOGO_CONFIG.get("playwright_aggressive_render", False)
                if aggressive:
                    wait_until = str(
                        LOGO_CONFIG.get("playwright_wait_until", "networkidle")
                        or "networkidle"
                    )
                    extra_ms = max(
                        int(LOGO_CONFIG.get("playwright_extra_wait_ms", 0) or 0),
                        2000,
                    )
                else:
                    wait_until = "domcontentloaded"
                    extra_ms = int(LOGO_CONFIG.get("playwright_extra_wait_ms", 0) or 0)

                page.goto(
                    state.website_url,
                    wait_until=wait_until,
                    timeout=TIMEOUTS["page_load_ms"],
                )
                if LOGO_CONFIG.get("playwright_wait_for_logo_selectors", True):
                    for sel in (
                        "header img",
                        ".logo img",
                        "[class*='logo'] img",
                        "nav img",
                    ):
                        try:
                            page.wait_for_selector(sel, timeout=3000)
                            break
                        except Exception:
                            continue

                page.wait_for_timeout(TIMEOUTS["page_render_wait_ms"] + extra_ms)

                if LOGO_CONFIG.get("playwright_extract_computed_background", True):
                    try:
                        raw_urls = page.evaluate(
                            """
                            () => {
                              function parseBgUrl(bg) {
                                if (!bg || bg === 'none') return null;
                                const i = bg.indexOf('url(');
                                if (i < 0) return null;
                                let rest = bg.slice(i + 4).trim();
                                let u = '';
                                if (rest[0] === '"' || rest[0] === "'") {
                                  const q = rest[0];
                                  const end = rest.indexOf(q, 1);
                                  if (end > 0) u = rest.slice(1, end);
                                } else {
                                  const end = rest.indexOf(')');
                                  if (end > 0) u = rest.slice(0, end).trim();
                                }
                                return u && !u.startsWith('data:') ? u : null;
                              }
                              const selectors = [
                                '.main_logo', '.navbar-brand',
                                '.logo', '#logo', '.site-logo', '.brand-logo',
                                '.header-logo',
                                'header a[href="/"]', 'nav a[href="/"]',
                                "[class*='logo']"
                              ];
                              const urls = [];
                              const seen = new Set();
                              for (const sel of selectors) {
                                try {
                                  document.querySelectorAll(sel).forEach(el => {
                                    const bg = getComputedStyle(el).backgroundImage;
                                    const u = parseBgUrl(bg);
                                    if (u && !seen.has(u)) { seen.add(u); urls.push(u); }
                                  });
                                } catch (e) {}
                              }
                              return urls;
                            }
                            """
                        )
                        for u in raw_urls or []:
                            if not u or str(u).startswith("data:"):
                                continue
                            abs_u = make_absolute_url(str(u).strip(), base_url)
                            extra_candidates.append({
                                "src": abs_u,
                                "alt": "logo",
                                "class": "computed-bg",
                                "in_header": True,
                                "is_home_link": False,
                                "is_first_in_nav": False,
                                "priority_selector": True,
                                "ancestor_href": None,
                                "width": None,
                                "height": None,
                            })
                    except Exception:
                        pass

                if LOGO_CONFIG.get("playwright_header_media_extras", True):
                    try:
                        raw_media = page.evaluate(_PLAYWRIGHT_HEADER_MEDIA_JS)
                        for u in raw_media or []:
                            if not u or str(u).startswith("data:"):
                                continue
                            abs_u = make_absolute_url(str(u).strip(), base_url)
                            extra_candidates.append({
                                "src": abs_u,
                                "alt": "logo",
                                "class": "header-media",
                                "in_header": True,
                                "is_home_link": False,
                                "is_first_in_nav": False,
                                "priority_selector": True,
                                "ancestor_href": None,
                                "width": None,
                                "height": None,
                            })
                    except Exception:
                        pass

                html = page.content()
                browser.close()
                return html, extra_candidates
            finally:
                pw.stop()

        try:
            rendered_html, extra_pw = await asyncio.to_thread(_render_page)
            soup = BeautifulSoup(rendered_html, "html.parser")

            # Extract logo candidates from rendered DOM using priority selectors
            pw_candidates = self._extract_logo_candidates_from_soup(soup, base_url)
            seen_src = {c["src"] for c in pw_candidates}
            for c in extra_pw:
                if c["src"] not in seen_src:
                    seen_src.add(c["src"])
                    pw_candidates.append(c)

            if not pw_candidates:
                self.log("Playwright: no candidates found")
                return False

            pw_scored = rank_logo_candidates(
                pw_candidates, base_url, company_slug=company_slug
            )
            self.log(f"Playwright: {len(pw_scored)} candidates, best={pw_scored[0][0] if pw_scored else -999}")

            for pw_score, pw_url in pw_scored[:5]:
                if self.should_stop():
                    break
                if pw_score <= 0:
                    break
                result = await self._try_download(pw_url, state, company_name)
                if result:
                    return True

            # Try Playwright-discovered favicon
            pw_favicon = self._extract_favicon_from_soup(soup, base_url)
            if pw_favicon and pw_favicon != state.favicon_url:
                self.log(f"Playwright favicon: {pw_favicon}")
                result = await self._try_download(pw_favicon, state, company_name)
                if result:
                    return True

            return False
        except Exception as e:
            self.log(f"Playwright failed: {e}", level="warning")
            return False

    def _extract_logo_candidates_from_soup(
        self, soup: BeautifulSoup, base_url: str
    ) -> List[Dict[str, Any]]:
        """Extract logo candidate images from nav/header of a BeautifulSoup tree."""
        candidates: List[Dict[str, Any]] = []
        seen: set = set()

        priority_selectors = [
            ".logo img", "#logo img",
            ".site-logo img", ".brand-logo img",
            ".navbar-brand img", ".nav-logo img",
            ".header-logo img", ".site-header__logo img",
            "a.logo img", "a.brand img",
            f"header a[href='/'] img", f"nav a[href='/'] img",
            ".header__logo img", ".c-header__logo img",
            "[class*='logo'] img", "[id*='logo'] img",
            "[aria-label*='logo' i] img",
        ]

        for sel in priority_selectors:
            try:
                for img_tag in soup.select(sel):
                    src = self._get_img_src(img_tag)
                    if not src:
                        continue
                    src = make_absolute_url(src, base_url)
                    if src in seen:
                        continue
                    seen.add(src)
                    w_raw = img_tag.get("width", "")
                    h_raw = img_tag.get("height", "")
                    # Check ancestor link
                    ancestor_href = self._find_ancestor_href(img_tag, base_url)
                    is_home = (
                        is_home_like_href(ancestor_href, base_url)
                        if ancestor_href else False
                    )
                    candidates.append({
                        "src": src,
                        "alt": img_tag.get("alt", ""),
                        "class": " ".join(img_tag.get("class", [])),
                        "in_header": True,
                        "is_home_link": is_home,
                        "is_first_in_nav": is_home,
                        "priority_selector": True,
                        "ancestor_href": ancestor_href,
                        "width": int(w_raw) if str(w_raw).isdigit() else None,
                        "height": int(h_raw) if str(h_raw).isdigit() else None,
                    })
            except Exception:
                continue

        # Full scan of header/nav images
        for container in soup.select("header, nav, [role='banner']"):
            for img_tag in container.find_all("img"):
                src = self._get_img_src(img_tag)
                if not src:
                    continue
                src = make_absolute_url(src, base_url)
                if src in seen:
                    continue
                seen.add(src)
                w_raw = img_tag.get("width", "")
                h_raw = img_tag.get("height", "")
                ancestor_href = self._find_ancestor_href(img_tag, base_url)
                is_home = (
                    is_home_like_href(ancestor_href, base_url)
                    if ancestor_href else False
                )
                candidates.append({
                    "src": src,
                    "alt": img_tag.get("alt", ""),
                    "class": " ".join(img_tag.get("class", [])),
                    "in_header": True,
                    "is_home_link": is_home,
                    "is_first_in_nav": len(candidates) == 0,
                    "priority_selector": False,
                    "ancestor_href": ancestor_href,
                    "width": int(w_raw) if str(w_raw).isdigit() else None,
                    "height": int(h_raw) if str(h_raw).isdigit() else None,
                })

        # ── Inline <svg> extraction (header/nav/banner/logo containers) ──
        _LOGO_KW_RE = re.compile(r'logo|brand|site-mark', re.IGNORECASE)
        svg_selectors = [
            "header svg", "nav svg", "[role='banner'] svg",
            ".logo svg", "#logo svg", "[class*='logo'] svg",
            "[data-framer-name*='Logo' i] svg",
            "a[href='/'] svg", "a[href$='/'] svg",
        ]
        for sel in svg_selectors:
            try:
                for svg_el in soup.select(sel):
                    # Filter out tiny icon SVGs
                    vb = svg_el.get("viewBox", "")
                    if vb:
                        parts = vb.split()
                        if len(parts) == 4:
                            try:
                                vw, vh = float(parts[2]), float(parts[3])
                                if vw < 32 and vh < 32 and abs(vw - vh) < 2:
                                    continue  # tiny square icon
                            except (ValueError, IndexError):
                                pass

                    # Check for logo signals in SVG or ancestor classes
                    svg_classes = " ".join(svg_el.get("class", []))
                    aria_label = svg_el.get("aria-label", "")
                    title_tag = svg_el.find("title")
                    title_text = title_tag.get_text(strip=True) if title_tag else ""
                    has_logo_signal = (
                        _LOGO_KW_RE.search(svg_classes)
                        or _LOGO_KW_RE.search(aria_label)
                        or _LOGO_KW_RE.search(title_text)
                        or _LOGO_KW_RE.search(sel)
                    )

                    # Serialize SVG to data URI
                    svg_str = str(svg_el)
                    if len(svg_str) < 300:
                        continue  # too small — likely UI icon
                    svg_b64 = base64.b64encode(svg_str.encode("utf-8")).decode("ascii")
                    data_uri = f"data:image/svg+xml;base64,{svg_b64}"
                    if data_uri in seen:
                        continue
                    seen.add(data_uri)

                    ancestor_href = self._find_ancestor_href(svg_el, base_url)
                    is_home = (
                        is_home_like_href(ancestor_href, base_url)
                        if ancestor_href else False
                    )
                    candidates.append({
                        "src": data_uri,
                        "alt": title_text or aria_label or "logo",
                        "class": svg_classes,
                        "in_header": True,
                        "is_home_link": is_home,
                        "is_first_in_nav": len(candidates) == 0,
                        "priority_selector": has_logo_signal,
                        "ancestor_href": ancestor_href,
                        "width": None,
                        "height": None,
                    })
            except Exception:
                continue

        # ── CSS background-image extraction on logo containers ───────────
        _BG_RE = re.compile(r'background(?:-image)?\s*:\s*url\(["\']?([^"\')\s]+)', re.IGNORECASE)
        bg_selectors = [
            ".main_logo", ".navbar-brand",
            ".logo", "#logo", ".site-logo", ".brand-logo",
            ".header-logo", "[class*='logo']",
            "header a[href='/']", "nav a[href='/']",
        ]
        for sel in bg_selectors:
            try:
                for el in soup.select(sel):
                    style = el.get("style", "")
                    if not style:
                        continue
                    match = _BG_RE.search(style)
                    if not match:
                        continue
                    bg_url = match.group(1).strip()
                    bg_url = make_absolute_url(bg_url, base_url)
                    if bg_url in seen:
                        continue
                    seen.add(bg_url)
                    ancestor_href = self._find_ancestor_href(el, base_url)
                    is_home = (
                        is_home_like_href(ancestor_href, base_url)
                        if ancestor_href else False
                    )
                    candidates.append({
                        "src": bg_url,
                        "alt": "logo",
                        "class": " ".join(el.get("class", [])),
                        "in_header": True,
                        "is_home_link": is_home,
                        "is_first_in_nav": False,
                        "priority_selector": True,
                        "ancestor_href": ancestor_href,
                        "width": None,
                        "height": None,
                    })
            except Exception:
                continue

        return candidates

    @staticmethod
    def _get_img_src(img_tag) -> Optional[str]:
        """Get the best src from an <img> tag (handles lazy-load attrs)."""
        for attr in ("src", "data-src", "data-lazy-src", "data-original", "srcset"):
            val = (img_tag.get(attr) or "").strip()
            if val and not val.startswith("data:image/svg+xml"):
                if attr == "srcset":
                    val = val.split(",")[0].split()[0]
                return val
        return None

    @staticmethod
    def _find_ancestor_href(tag, base_url: str) -> Optional[str]:
        """Walk up the DOM to find the nearest ancestor <a> href."""
        node = tag.parent
        for _ in range(6):
            if not node or node.name in ("[document]", "body", "html"):
                break
            if node.name == "a" and node.get("href"):
                href = node["href"].strip()
                if href and not href.startswith("#") and not href.startswith("javascript:"):
                    return make_absolute_url(href, base_url)
            node = node.parent
        return None

    @staticmethod
    def _extract_favicon_from_soup(
        soup: BeautifulSoup, base_url: str
    ) -> Optional[str]:
        """Extract best favicon URL from link tags."""
        candidates: List[Tuple[int, str]] = []
        for link in soup.find_all("link", rel=True):
            rels = " ".join(link["rel"]).lower()
            href = link.get("href", "").strip()
            if not href:
                continue
            if "apple-touch-icon" in rels:
                candidates.append((1, make_absolute_url(href, base_url)))
            elif "icon" in rels:
                sizes = link.get("sizes", "")
                try:
                    w = int(sizes.split("x")[0])
                    priority = 2 if w >= 64 else 4
                except (ValueError, IndexError):
                    priority = 3
                candidates.append((priority, make_absolute_url(href, base_url)))
        candidates.sort(key=lambda c: c[0])
        return candidates[0][1] if candidates else None

    # ------------------------------------------------------------------
    # Strategy E: Gemini web search
    # ------------------------------------------------------------------
    async def _try_web_search(
        self, state: ScrapeState, company_name: str, base_url: str
    ) -> bool:
        """Use Gemini with Google Search grounding to find logo URLs."""
        try:
            from google.genai import types as gtypes

            prompt = LOGO_SEARCH_PROMPT.format(
                company_name=company_name,
                domain=state.domain or urlparse(base_url).netloc,
            )
            self.log(f"Web search: looking for {company_name} logo URL...")

            response = await aio_generate_content_with_fallback(
                self.gemini,
                self.text_models,
                contents=prompt,
                config=gtypes.GenerateContentConfig(
                    tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                    temperature=0,
                ),
            )

            resp_text = ""
            if response and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        resp_text += part.text
            resp_text = resp_text.strip()

            if not resp_text:
                self.log("Web search: empty response")
                return False

            # Extract URLs — try JSON first, fall back to regex
            logo_urls: List[str] = []
            try:
                parsed = json.loads(resp_text)
                logo_urls = parsed.get("logo_urls", [])
            except (json.JSONDecodeError, ValueError):
                pass

            if not logo_urls:
                logo_urls = re.findall(
                    r'https?://[^\s"\'<>]+\.(?:svg|png|webp|jpg|jpeg)(?:\?[^\s"\'<>]*)?',
                    resp_text,
                )
            if not logo_urls:
                logo_urls = re.findall(r'https?://[^\s"\'<>]+', resp_text)
            logo_urls = [u.rstrip('.,;)"\'') for u in logo_urls]

            # For Wikimedia SVGs, also add rasterized thumbnail
            extra_urls: List[str] = []
            for u in logo_urls:
                wm = re.match(
                    r'(https://upload\.wikimedia\.org/wikipedia/commons/)'
                    r'([0-9a-f]/[0-9a-f]{2}/(.+\.svg))$',
                    u, re.IGNORECASE,
                )
                if wm:
                    svg_path = wm.group(2)
                    svg_name = wm.group(3)
                    extra_urls.append(
                        f"{wm.group(1)}thumb/{svg_path}/400px-{svg_name}.png"
                    )
            logo_urls = logo_urls + extra_urls

            for ws_url in logo_urls[:6]:
                if self.should_stop():
                    break
                self.log(f"Web search URL: {ws_url}")
                result = await self._try_download(ws_url, state, company_name)
                if result:
                    return True

            self.log("Web search: no usable logo URL found")
            return False

        except Exception as e:
            self.log(f"Web search failed: {e}", level="warning")
            return False

    # ------------------------------------------------------------------
    # Strategy F: Wikipedia pageimages API
    # ------------------------------------------------------------------
    async def _try_wikipedia(self, state: ScrapeState, company_name: str) -> bool:
        """Try the Wikipedia pageimages API for well-known brands."""
        try:
            wiki_api_url = "https://en.wikipedia.org/w/api.php"
            params = {
                "action": "query",
                "prop": "pageimages",
                "titles": company_name.strip(),
                "pithumbsize": 500,
                "format": "json",
                "redirects": 1,
            }
            response = await asyncio.to_thread(
                lambda: requests.get(
                    wiki_api_url,
                    params=params,
                    timeout=8,
                    headers=DEFAULT_HEADERS,
                )
            )
            if response.status_code != 200:
                return False

            data = response.json()
            pages = data.get("query", {}).get("pages", {})
            for page in pages.values():
                thumb_url = (page.get("thumbnail") or {}).get("source")
                if thumb_url:
                    self.log(f"Wikipedia thumbnail: {thumb_url}")
                    result = await self._try_download(thumb_url, state, company_name)
                    if result:
                        return True
                break  # only check first page

            return False
        except Exception as e:
            self.log(f"Wikipedia API failed: {e}", level="warning")
            return False

    # ------------------------------------------------------------------
    # Strategy G: Public APIs
    # ------------------------------------------------------------------
    async def _try_public_apis(self, state: ScrapeState, company_name: str) -> bool:
        """Try Clearbit, DuckDuckGo, Google favicon APIs."""
        parsed_domain = urlparse(state.website_url).netloc.lstrip("www.")
        if not parsed_domain:
            return False

        api_urls = [
            f"https://logo.clearbit.com/{parsed_domain}",
            f"https://icons.duckduckgo.com/ip3/{parsed_domain}.ico",
            f"https://www.google.com/s2/favicons?domain={parsed_domain}&sz=128",
        ]

        for api_url in api_urls:
            if self.should_stop():
                break
            self.log(f"Public API: {api_url}")
            dl_result = await asyncio.to_thread(
                self._download_logo,
                api_url,
                state.scrape_id,
                company_name,
                TIMEOUTS["logo_download"],
            )
            if dl_result.get("success"):
                # Reject favicon-sized images (<100px)
                local_path = dl_result.get("local_path")
                if local_path:
                    try:
                        img = Image.open(local_path)
                        w, h = img.size
                        if w < 100 and h < 100:
                            self.log(f"Public API favicon too small ({w}x{h}px), skipping")
                            continue
                    except Exception:
                        pass

                state.logo_url = dl_result.get("original_url") or dl_result.get("url")
                state.logo_local_path = dl_result.get("local_path")
                state.logo_cloudinary_url = dl_result.get("cloudinary_url")
                state.logo_bytes = dl_result.get("logo_bytes")
                self.log(f"Public API succeeded: {state.logo_url}")
                return True
            else:
                self.log(f"Public API rejected: {dl_result.get('reason', 'unknown')}")

        return False

    # ------------------------------------------------------------------
    # Strategy I: URL path probing
    # ------------------------------------------------------------------
    async def _try_path_probing(
        self, state: ScrapeState, company_name: str, base_url: str
    ) -> bool:
        """Probe common logo paths on the site."""
        parsed = urlparse(base_url)
        probe_base = f"{parsed.scheme}://{parsed.netloc}"
        if not probe_base or "://" not in probe_base:
            return False

        self.log(f"Probing {len(_PROBE_PATHS)} common paths on {probe_base}")
        for path in _PROBE_PATHS:
            if self.should_stop():
                break
            probe_url = probe_base + path
            result = await self._try_download(
                probe_url, state, company_name, timeout=TIMEOUTS["logo_probe"]
            )
            if result:
                return True

        return False
