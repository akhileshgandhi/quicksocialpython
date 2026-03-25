"""
ContactSocialAgent — extracts social-media links and contact information.

Parses the homepage first, then checks the dedicated contact page
(if discovered by the CrawlerAgent) and merges the results.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from scraper_agents.agents.base import BaseAgent
from scraper_agents.state import ScrapeState
from scraper_agents.config import DEFAULT_HEADERS, TIMEOUTS
from scraper_agents.extractors.contact_extraction import (
    extract_social_links,
    extract_contact_info,
)

logger = logging.getLogger(__name__)


class ContactSocialAgent(BaseAgent):
    """Extracts social links and contact info from the website."""

    agent_name: str = "contact"

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def run(self, state: ScrapeState) -> None:
        if not state.homepage_soup:
            self.log("No homepage_soup available — skipping", level="warning")
            return

        # ── Step 1: Extract from homepage ─────────────────────────────
        social_links = extract_social_links(state.homepage_soup, state.base_url)
        contact_info = extract_contact_info(state.homepage_soup, state.base_url)

        self.log(
            f"Homepage: {len(social_links)} social platform(s), "
            f"emails={bool(contact_info.get('emails'))}, "
            f"phones={bool(contact_info.get('phones'))}"
        )

        # ── Step 2: Check contact page (if available) ─────────────────
        contact_pages = state.site_map.get("contact", [])
        if contact_pages:
            contact_url = contact_pages[0].url
            contact_soup = _get_page_soup(contact_url, state)
            if contact_soup:
                self.log(f"Parsing contact page: {contact_url}")

                contact_social = extract_social_links(contact_soup, contact_url)
                contact_contact = extract_contact_info(contact_soup, contact_url)

                # Merge social links — homepage wins for duplicates
                social_links = _merge_social(social_links, contact_social)

                # Merge contact info — combine lists, deduplicate
                contact_info = _merge_contact(contact_info, contact_contact)

                self.log(
                    f"After merge: {len(social_links)} social platform(s), "
                    f"emails={bool(contact_info.get('emails'))}, "
                    f"phones={bool(contact_info.get('phones'))}"
                )

        # ── Step 3: Write to state ────────────────────────────────────
        state.social_links = social_links
        state.contact_info = contact_info


# ======================================================================
# Private helpers
# ======================================================================


def _get_page_soup(url: str, state: ScrapeState) -> Optional[BeautifulSoup]:
    """Return a BeautifulSoup for *url*, using the page cache if available."""
    # Check cached HTML first
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
        logger.debug(f"[ContactSocialAgent] Failed to fetch {url}: {exc}")

    return None


def _merge_social(
    primary: Dict[str, Any],
    secondary: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge two social-link dicts. Primary wins for per-platform duplicates.

    The "other" lists are concatenated and deduplicated.
    """
    merged = dict(primary)
    for platform, url in secondary.items():
        if platform == "other":
            continue
        if platform not in merged:
            merged[platform] = url

    # Merge "other" lists
    primary_other: List[str] = primary.get("other", [])
    secondary_other: List[str] = secondary.get("other", [])
    if primary_other or secondary_other:
        seen = set(primary_other)
        combined = list(primary_other)
        for url in secondary_other:
            if url not in seen:
                seen.add(url)
                combined.append(url)
        if combined:
            merged["other"] = combined

    return merged


def _merge_contact(
    primary: Dict[str, Any],
    secondary: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge two contact-info dicts, combining and deduplicating list fields."""
    merged: Dict[str, Any] = {}

    # Merge list fields (emails, phones, addresses)
    for key in ("emails", "phones", "addresses"):
        p_list = primary.get(key) or []
        s_list = secondary.get(key) or []
        if p_list or s_list:
            seen: set = set()
            combined: List[str] = []
            for item in p_list + s_list:
                norm = item.strip().lower()
                if norm not in seen:
                    seen.add(norm)
                    combined.append(item)
            merged[key] = combined if combined else None
        else:
            merged[key] = None

    # contact_page_url — prefer primary
    merged["contact_page_url"] = (
        primary.get("contact_page_url") or secondary.get("contact_page_url")
    )

    return merged
