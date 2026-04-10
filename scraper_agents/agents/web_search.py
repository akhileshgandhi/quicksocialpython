"""
WebSearchAgent — fills data gaps via Gemini + Google Search grounding.

Runs after all extraction agents.  Only fills null/empty fields.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, List

from scraper_agents.agents.base import BaseAgent
from scraper_agents.prompts.gap_fill import GAP_FILL_PROMPT, SEARCHABLE_GAP_FIELDS
from scraper_agents.state import ScrapeState

logger = logging.getLogger(__name__)


def _extract_json(text: str) -> str:
    """Robustly extract JSON from Gemini response that may contain preamble."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            text = text[start:end]
    return text


class WebSearchAgent(BaseAgent):
    agent_name = "web_search"

    async def run(self, state: ScrapeState) -> None:
        # Identify gaps
        gaps = self._find_gaps(state)
        if not gaps:
            self.log("no searchable gaps found — skipping")
            return

        self.log(f"filling {len(gaps)} gaps: {gaps}")

        # Build prompt
        gap_text = "\n".join(f"- {g}" for g in gaps)
        prompt = GAP_FILL_PROMPT.format(
            company_name=state.company_name or state.domain,
            website_url=state.website_url,
            gap_fields=gap_text,
        )

        try:
            from google import genai
            from google.genai import types

            response = await asyncio.to_thread(
                self.gemini.models.generate_content,
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.1,
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            text = response.text or ""
            text = _extract_json(text)

            if not text.startswith("{"):
                self.log(f"non-JSON response: {text[:100]}", level="warning")
                return

            data = json.loads(text)
            self._apply_fills(state, data, gaps)

        except Exception as e:
            self.log(f"Gemini web search failed: {e}", level="warning")

    def _find_gaps(self, state: ScrapeState) -> List[str]:
        """Identify which searchable fields are empty."""
        gaps: List[str] = []

        bi = state.brand_identity
        if not bi.get("tagline") and "tagline" in SEARCHABLE_GAP_FIELDS:
            gaps.append("tagline")
        if not bi.get("brand_story") and "brand_story" in SEARCHABLE_GAP_FIELDS:
            gaps.append("brand_story")
        if not bi.get("competitor_diff") and "competitor_diff" in SEARCHABLE_GAP_FIELDS:
            gaps.append("competitor_diff")

        ci = state.contact_info
        if not ci.get("emails") and "contact_info.emails" in SEARCHABLE_GAP_FIELDS:
            gaps.append("contact_info.emails")
        if not ci.get("phones") and "contact_info.phones" in SEARCHABLE_GAP_FIELDS:
            gaps.append("contact_info.phones")
        if not ci.get("addresses") and "contact_info.addresses" in SEARCHABLE_GAP_FIELDS:
            gaps.append("contact_info.addresses")

        if not state.products and "products" in SEARCHABLE_GAP_FIELDS:
            gaps.append("products")
        if not state.services and "services" in SEARCHABLE_GAP_FIELDS:
            gaps.append("services")

        return gaps

    def _apply_fills(self, state: ScrapeState, data: Dict, gaps: List[str]) -> None:
        """Apply web search results — only fill empty fields."""
        if "tagline" in gaps and data.get("tagline"):
            tagline = data["tagline"]
            # Gemini may return a dict/list instead of string — coerce
            if isinstance(tagline, dict):
                tagline = next(iter(tagline.values()), "") if tagline else ""
                if isinstance(tagline, list):
                    tagline = tagline[0] if tagline else ""
            elif isinstance(tagline, list):
                tagline = tagline[0] if tagline else ""
            if isinstance(tagline, str) and tagline:
                state.brand_identity["tagline"] = tagline
                self.log(f"filled tagline: {tagline[:50]}")

        if "brand_story" in gaps and data.get("brand_story"):
            state.brand_identity["brand_story"] = data["brand_story"]
            self.log("filled brand_story")

        if "competitor_diff" in gaps and data.get("competitor_diff"):
            state.brand_identity["competitor_diff"] = data["competitor_diff"]
            self.log("filled competitor_diff")

        if "contact_info.emails" in gaps and data.get("contact_emails"):
            if not state.contact_info.get("emails"):
                state.contact_info["emails"] = data["contact_emails"]
                self.log(f"filled {len(data['contact_emails'])} emails")

        if "contact_info.phones" in gaps and data.get("contact_phones"):
            if not state.contact_info.get("phones"):
                state.contact_info["phones"] = data["contact_phones"]
                self.log(f"filled {len(data['contact_phones'])} phones")

        if "contact_info.addresses" in gaps and data.get("contact_addresses"):
            if not state.contact_info.get("addresses"):
                state.contact_info["addresses"] = data["contact_addresses"]

        if "products" in gaps and data.get("products"):
            if not state.products:
                state.products = data["products"]
                self.log(f"filled {len(data['products'])} products")
                # Try to match image URLs from cached pages
                self._match_websearch_product_images(state)

        if "services" in gaps and data.get("services"):
            if not state.services:
                state.services = data["services"]
                self.log(f"filled {len(data['services'])} services")

    def _match_websearch_product_images(self, state: ScrapeState) -> None:
        """Match image URLs from cached pages to WebSearch-filled products.

        WebSearch returns product names but no image URLs. The cached pages
        may contain ``<img>`` tags with product images we can match by name.
        """
        if not state.page_cache or not state.products:
            return

        from bs4 import BeautifulSoup
        from scraper_agents.extractors.html_helpers import extract_all_images

        # Collect candidate images from cached pages
        candidate_images: list = []
        _SKIP = {"icon", "logo", "arrow", "chevron", "close", "menu",
                 "search", "spinner", "banner", "hero", "caret",
                 "hamburger", "social", "tracking", "pixel"}
        for _, cache_html in state.page_cache.items():
            try:
                soup = BeautifulSoup(cache_html, "html.parser")
                for img in extract_all_images(soup, state.base_url, limit=50):
                    src = (img.get("src") or "").lower()
                    if src and not src.endswith(".svg") and not any(kw in src for kw in _SKIP):
                        candidate_images.append(img)
            except Exception:
                pass
        # Also homepage images
        for img in (state.images or []):
            src = (img.get("src") or "").lower()
            if src and not src.endswith(".svg") and not any(kw in src for kw in _SKIP):
                candidate_images.append(img)

        if not candidate_images:
            return

        company_words = set()
        if state.company_name:
            company_words = set(re.findall(r'[a-z]{4,}', state.company_name.lower()))

        matched = 0
        for product in state.products:
            if product.get("image_urls"):
                continue
            pname = (product.get("name") or "").lower().strip()
            if not pname or len(pname) < 3:
                continue

            pname_words = set(re.findall(r'[a-z]{4,}', pname)) - company_words
            if not pname_words:
                continue

            best_url = None
            best_score = 0.0
            min_score = 1.0 if len(pname_words) == 1 else 0.5

            for img in candidate_images:
                alt = (img.get("alt") or "").lower()
                src = (img.get("src") or "").lower()
                fn = src.rsplit("/", 1)[-1].split("?")[0] if "/" in src else src
                fn_clean = fn.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").lower()

                alt_words = set(re.findall(r'[a-z]{4,}', alt))
                fn_words = set(re.findall(r'[a-z]{4,}', fn_clean))
                alt_score = len(pname_words & alt_words) / len(pname_words)
                fn_score = len(pname_words & fn_words) / len(pname_words)
                score = max(alt_score, fn_score)

                if score >= min_score and score > best_score:
                    best_score = score
                    best_url = img.get("src")

            if best_url:
                product["image_urls"] = [best_url]
                matched += 1

        if matched:
            self.log(f"matched {matched} product images from cached pages")
