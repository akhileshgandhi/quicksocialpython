"""
BrandIntelligenceAgent — synthesizes all extracted data into brand identity.

Runs after all Phase 2 agents complete.  Makes one Gemini call with
pre-resolved products/colors/fonts for a smaller, more focused prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict

from scraper_agents.agents.base import BaseAgent
from scraper_agents.extractors.html_helpers import infer_country_from_tld
from scraper_agents.prompts.brand_analysis import BRAND_ANALYSIS_PROMPT
from scraper_agents.state import ScrapeState

logger = logging.getLogger(__name__)

# ISO 3166-1 alpha-2 → common English country name
_ISO_TO_COUNTRY = {
    "IN": "India", "US": "United States", "GB": "United Kingdom",
    "AE": "UAE", "SG": "Singapore", "AU": "Australia", "CA": "Canada",
    "DE": "Germany", "FR": "France", "JP": "Japan", "KR": "South Korea",
    "CN": "China", "BR": "Brazil", "SA": "Saudi Arabia", "OM": "Oman",
    "NP": "Nepal", "LK": "Sri Lanka", "BD": "Bangladesh", "PK": "Pakistan",
    "ID": "Indonesia", "MY": "Malaysia", "TH": "Thailand", "VN": "Vietnam",
    "PH": "Philippines", "NZ": "New Zealand", "ZA": "South Africa",
    "NG": "Nigeria", "KE": "Kenya", "EG": "Egypt", "TR": "Turkey",
    "IT": "Italy", "ES": "Spain", "NL": "Netherlands", "SE": "Sweden",
    "NO": "Norway", "DK": "Denmark", "FI": "Finland", "PL": "Poland",
    "RU": "Russia", "MX": "Mexico", "AR": "Argentina", "CO": "Colombia",
    "CL": "Chile", "PE": "Peru", "IE": "Ireland", "CH": "Switzerland",
    "AT": "Austria", "BE": "Belgium", "PT": "Portugal", "IL": "Israel",
    "QA": "Qatar", "BH": "Bahrain", "KW": "Kuwait",
}


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


class BrandIntelligenceAgent(BaseAgent):
    agent_name = "brand_intelligence"

    async def run(self, state: ScrapeState) -> None:
        # Brief pause to let parallel agents (Visual, Contact) write initial data
        await asyncio.sleep(2)
        # Build prompt with pre-resolved data
        products_text = self._format_products(state.products[:20])
        services_text = self._format_services(state.services[:10])
        headings_text = "\n".join(
            f"- [{h['level']}] {h['text']}" for h in state.headings[:20]
        )
        social_text = ", ".join(
            f"{k}: {v}" for k, v in state.social_links.items() if v
        ) or "(none found)"
        # Send actual content titles (not asset types) so Gemini can infer themes
        asset_titles = [
            a.get("title", "") for a in state.content_assets
            if a.get("title") and a.get("title") not in ("Video", "Gallery image")
        ]
        content_themes = ", ".join(asset_titles[:15]) if asset_titles else "(none)"

        country = infer_country_from_tld(state.website_url)

        prompt = BRAND_ANALYSIS_PROMPT.format(
            company_name=state.company_name or state.domain,
            website_url=state.website_url,
            site_type=state.site_type or "unknown",
            country=country or "(infer from content)",
            title=state.title,
            meta_description=state.meta_description[:500],
            headings_text=headings_text or "(none)",
            about_content=state.about_content[:3000] or "(not found)",
            full_text_excerpt=state.full_text[:2000] if state.full_text else "(none)",
            product_count=len(state.products),
            products_text=products_text or "(none found)",
            service_count=len(state.services),
            services_text=services_text or "(none found)",
            brand_colors=", ".join(state.primary_color) if state.primary_color else "(not determined)",
            headline_font=state.headline_font or "(not determined)",
            body_font=state.body_font or "(not determined)",
            content_themes_text=content_themes,
            social_links_text=social_text,
        )

        try:
            from google import genai

            response = await asyncio.to_thread(
                self.gemini.models.generate_content,
                model=self.model,
                contents=prompt,
                config=genai.types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                ),
            )
            self.track_usage(response, "brand_analysis", state)
            text = response.text or ""
            text = _extract_json(text)

            if not text.startswith("{"):
                self.log(f"non-JSON response: {text[:200]}", level="warning")
                self._fallback(state)
                return

            data = json.loads(text)

            # Apply brand identity
            bi = data.get("brand_identity", {})
            # Ensure name is always set
            bi.setdefault("name", state.company_name or state.domain)
            # Apply country from TLD if Gemini didn't provide one
            if not bi.get("country") and country:
                bi["country"] = country
            # Normalize ISO codes to full country names
            country_val = bi.get("country", "")
            if country_val and len(country_val) == 2:
                bi["country"] = _ISO_TO_COUNTRY.get(
                    country_val.upper(), country_val
                )
            state.brand_identity = bi

            # Apply SEO/social
            state.seo_social = data.get("seo_social", {})

            # Track gaps
            state.data_gaps = data.get("data_gaps", [])

            self.log(f"brand: {bi.get('name')}, industry: {bi.get('industry')}, "
                     f"gaps: {len(state.data_gaps)}")

        except json.JSONDecodeError as e:
            self.log(f"JSON parse failed: {e}", level="warning")
            self._fallback(state)
        except Exception as e:
            self.log(f"Gemini brand analysis failed: {e}", level="warning")
            self._fallback(state)

    def _fallback(self, state: ScrapeState) -> None:
        """Minimal brand identity when Gemini fails."""
        iso = infer_country_from_tld(state.website_url)
        state.brand_identity = {
            "name": state.company_name or state.domain,
            "about": state.meta_description or None,
            "country": _ISO_TO_COUNTRY.get(iso.upper(), iso) if iso else None,
        }
        state.seo_social = {}

    @staticmethod
    def _format_products(products: list) -> str:
        lines = []
        for p in products:
            name = p.get("name", "Unknown")
            cat = p.get("category", "")
            price = p.get("price", "")
            desc = (p.get("description") or "")[:100]
            line = f"- {name}"
            if cat:
                line += f" [{cat}]"
            if price:
                line += f" ({price})"
            if desc:
                line += f": {desc}"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _format_services(services: list) -> str:
        lines = []
        for s in services:
            name = s.get("name", "Unknown")
            cat = s.get("category", "")
            desc = (s.get("description") or "")[:100]
            line = f"- {name}"
            if cat:
                line += f" [{cat}]"
            if desc:
                line += f": {desc}"
            lines.append(line)
        return "\n".join(lines)
