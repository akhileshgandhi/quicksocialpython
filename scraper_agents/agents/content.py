"""
ContentAssetsAgent — finds blogs, case studies, testimonials, videos,
downloadable files, and gallery images.

Extracts from the homepage first, then scans blog / gallery pages
discovered by the CrawlerAgent.  Enriches assets by fetching detail
pages concurrently (thumbnail, description, download link).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Set

import requests
from bs4 import BeautifulSoup

from scraper_agents.agents.base import BaseAgent
from scraper_agents.state import ScrapeState
from scraper_agents.config import CONCURRENCY, DEFAULT_HEADERS, TIMEOUTS
from scraper_agents.extractors.content_parsing import (
    extract_content_assets,
    enrich_content_assets,
)

logger = logging.getLogger(__name__)

# Site-map categories whose pages are worth scanning for content assets
_CONTENT_PAGE_CATEGORIES = {"blog", "gallery", "portfolio", "news", "resources"}


class ContentAssetsAgent(BaseAgent):
    """Discovers and enriches content assets across the website."""

    agent_name: str = "content"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, state: ScrapeState) -> None:
        if not state.homepage_soup:
            self.log("No homepage_soup available — skipping", level="warning")
            return

        # ── Step 1: Extract from homepage ─────────────────────────────
        assets = extract_content_assets(state.homepage_soup, state.base_url)
        self.log(f"Homepage extraction found {len(assets)} asset(s)")

        if self.should_stop():
            state.content_assets = assets
            return

        # ── Step 2: Extract from cached content pages ─────────────────
        content_pages = _collect_content_pages(state)
        if content_pages:
            self.log(f"Scanning {len(content_pages)} additional content page(s)")

        seen_urls: Set[str] = {a.get("url", "") for a in assets if a.get("url")}

        for page_url in content_pages:
            if self.should_stop():
                self.log("Time budget reached — stopping page scanning")
                break

            page_soup = _get_page_soup(page_url, state)
            if not page_soup:
                continue

            page_assets = extract_content_assets(page_soup, page_url)
            # Merge new assets, skipping duplicates by URL
            for asset in page_assets:
                asset_url = asset.get("url", "")
                if asset_url and asset_url in seen_urls:
                    continue
                if asset_url:
                    seen_urls.add(asset_url)
                assets.append(asset)

            self.log(f"  {page_url} yielded {len(page_assets)} asset(s)")

        self.log(f"Total assets before enrichment: {len(assets)}")

        if self.should_stop():
            state.content_assets = assets
            return

        # ── Step 3: Enrich assets (concurrent detail page fetching) ───
        enrichable = [a for a in assets if a.get("url")]
        if enrichable:
            self.log(f"Enriching up to {CONCURRENCY['max_asset_enrichments']} asset(s)")
            # enrich_content_assets uses ThreadPoolExecutor internally
            assets = await asyncio.to_thread(
                enrich_content_assets,
                assets,
                state.base_url,
            )

        # ── Step 4: Write to state ────────────────────────────────────
        state.content_assets = assets
        self.log(f"Final content assets: {len(assets)}")


# ======================================================================
# Private helpers
# ======================================================================


def _collect_content_pages(state: ScrapeState) -> List[str]:
    """Gather URLs for blog / gallery / portfolio pages from the site map."""
    pages: List[str] = []
    seen: set = set()

    for category in _CONTENT_PAGE_CATEGORIES:
        for page_info in state.site_map.get(category, []):
            url = page_info.url
            if url and url not in seen:
                seen.add(url)
                pages.append(url)

    return pages


def _get_page_soup(url: str, state: ScrapeState) -> Optional[BeautifulSoup]:
    """Return a BeautifulSoup for *url*, using the page cache if available."""
    cached_html = state.page_cache.get(url)
    if cached_html:
        return BeautifulSoup(cached_html, "html.parser")

    # Fetch live
    try:
        resp = requests.get(
            url,
            headers=DEFAULT_HEADERS,
            timeout=TIMEOUTS["http_request"],
            allow_redirects=True,
        )
        if resp.status_code == 200:
            return BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.debug(f"[ContentAssetsAgent] Failed to fetch {url}: {exc}")

    return None
