"""
Pure-function extractors for social links and contact information.

Ported from scraper.py — no AI calls, no state mutation.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from bs4 import BeautifulSoup

from urllib.parse import urlparse, urlunparse

from .html_helpers import make_absolute_url


# ── Social-media domain map ──────────────────────────────────────────────────

_SOCIAL_PLATFORMS: Dict[str, List[str]] = {
    "facebook":  ["facebook.com", "fb.com"],
    "instagram": ["instagram.com"],
    "twitter":   ["twitter.com", "x.com"],
    "linkedin":  ["linkedin.com"],
    "youtube":   ["youtube.com", "youtu.be"],
    "tiktok":    ["tiktok.com"],
    "pinterest": ["pinterest.com"],
    "github":    ["github.com"],
}


def _clean_social_url(url: str) -> str:
    """Strip tracking params and fragments from social profile URLs."""
    try:
        parsed = urlparse(url)
        # For non-YouTube, strip ALL query params (always tracking/referral)
        if "youtube.com" not in parsed.netloc and "youtu.be" not in parsed.netloc:
            return urlunparse(parsed._replace(query="", fragment=""))
        # YouTube: keep channel/user URLs clean, leave video URLs as-is
        path = parsed.path
        if any(seg in path for seg in ["/channel/", "/c/", "/user/", "/@"]):
            return urlunparse(parsed._replace(query="", fragment=""))
        return url
    except Exception:
        return url


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_social_links(soup: BeautifulSoup, base_url: str) -> Dict[str, Any]:
    """Find social-media profile URLs in footer / nav / full page.

    Returns a dict keyed by platform name (facebook, instagram, …).
    An ``"other"`` key holds a list of unrecognised social-looking links.
    Only the first match per platform is kept.
    """
    found: Dict[str, str] = {}
    other: List[str] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if not href or href.startswith(("#", "javascript:", "tel:", "mailto:", "data:")):
            continue

        href_lower = href.lower()
        matched = False
        for platform, domains in _SOCIAL_PLATFORMS.items():
            if any(domain in href_lower for domain in domains):
                if platform not in found:
                    found[platform] = _clean_social_url(href)
                matched = True
                break

        if not matched:
            # Check for other social-like patterns (rel="me", social in class)
            rel = a_tag.get("rel", [])
            cls = " ".join(a_tag.get("class", [])).lower()
            if re.search(r"\bsocial\b", cls) or "me" in rel:
                # Only add external URLs — skip internal site links
                if href.startswith(("http://", "https://", "//")):
                    other.append(_clean_social_url(href))

    # Build result in canonical platform order
    result: Dict[str, Any] = {}
    for platform in _SOCIAL_PLATFORMS:
        if platform in found:
            result[platform] = found[platform]

    if other:
        # Deduplicate preserving order
        result["other"] = list(dict.fromkeys(other))

    return result


def extract_contact_info(soup: BeautifulSoup, base_url: str) -> Dict[str, Any]:
    """Extract emails, phone numbers, addresses, and contact-page URL.

    Sources (in priority order):
    - ``mailto:`` / ``tel:`` links (most reliable)
    - Regex over full page text
    - JSON-LD structured data for addresses
    - Footer / contact-section heuristics for addresses
    - ``<a>`` with "contact" in href or text for the contact page URL
    """
    # Lower-case key → original-case value (case-insensitive dedup)
    emails_lower: Dict[str, str] = {}
    phones: List[str] = []
    phones_seen: set = set()
    addresses: List[str] = []

    full_text = soup.get_text(separator=" ", strip=True)

    # ── Emails from mailto: links ─────────────────────────────────────────
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if email and "@" in email:
                emails_lower[email.lower()] = email
        elif href.startswith("tel:"):
            phone = href.replace("tel:", "").strip()
            phone = re.sub(r"[^\d\+\-\s]", "", phone).strip()
            digits = re.sub(r"[^\d]", "", phone)
            if 7 <= len(digits) <= 15 and digits not in phones_seen:
                phones_seen.add(digits)
                phones.append(phone)

    # ── Emails from page text ─────────────────────────────────────────────
    _EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    _BAD_EXTENSIONS = (
        ".png", ".jpg", ".gif", ".svg", ".webp", ".css", ".js",
        ".woff", ".ttf", ".eot", ".ico",
    )
    for match in _EMAIL_RE.findall(full_text):
        if not match.endswith(_BAD_EXTENSIONS):
            emails_lower[match.lower()] = match

    # ── Phone numbers from page text (strict pattern) ─────────────────────
    _PHONE_RE = re.compile(
        r"(?<![/\w@])"
        r"(\+?\d{1,4}[\s\-\.]?\(?\d{2,5}\)?[\s\-\.]?\d{2,5}[\s\-\.]?\d{0,4})"
        r"(?![/\w@])"
    )
    for match in _PHONE_RE.findall(full_text):
        cleaned = match.strip()
        # Reject: contains slash, @, letters, or path-like patterns
        if any(c in cleaned for c in ["/", "@", "\\"]) or re.search(r"[a-zA-Z]", cleaned):
            continue
        digits = re.sub(r"[^\d]", "", cleaned)
        if not (8 <= len(digits) <= 15):
            continue
        # Reject year ranges like 1996-2015
        _yr = re.match(r"^(\d{4})[\s\-](\d{4})$", cleaned.strip())
        if _yr and 1800 <= int(_yr.group(1)) <= 2100 and 1800 <= int(_yr.group(2)) <= 2100:
            continue
        # Reject pincode-prefixed numbers (e.g. "452001 6262 3000")
        if len(digits) >= 12:
            prefix6 = digits[:6]
            if 100000 <= int(prefix6) <= 999999:
                # Likely Indian pincode + phone — strip pincode
                stripped = digits[6:]
                if 7 <= len(stripped) <= 12:
                    digits = stripped
                    cleaned = "+" + stripped
                else:
                    continue
        digits_key = digits
        if digits_key not in phones_seen:
            phones_seen.add(digits_key)
            phones.append(cleaned)

    # Deduplicate suffix-overlapping phones (e.g. +916262300030 and 6262300030)
    if len(phones) > 1:
        digit_keys = [re.sub(r"[^\d]", "", p) for p in phones]
        to_remove: set = set()
        for i, dk_i in enumerate(digit_keys):
            for j, dk_j in enumerate(digit_keys):
                if i != j and dk_i.endswith(dk_j) and len(dk_i) > len(dk_j):
                    to_remove.add(j)
        if to_remove:
            phones = [p for idx, p in enumerate(phones) if idx not in to_remove]

    # ── Addresses from JSON-LD structured data ────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            items = data if isinstance(data, list) else [data]
            for item in items:
                addr = item.get("address") or {}
                if isinstance(addr, dict) and addr.get("streetAddress"):
                    parts = [
                        addr.get("streetAddress", ""),
                        addr.get("addressLocality", ""),
                        addr.get("addressRegion", ""),
                        addr.get("postalCode", ""),
                        addr.get("addressCountry", ""),
                    ]
                    address_str = ", ".join(p for p in parts if p)
                    if address_str:
                        addresses.append(address_str)
        except Exception:
            pass

    # ── Addresses from footer / contact sections ──────────────────────────
    _ADDR_RE = re.compile(
        r"\b(street|road|avenue|ave[\.,]|blvd|boulevard|suite|floor"
        r"|zip\s*code|pin\s*code|postal\s*code)\b",
        re.IGNORECASE,
    )
    for section in soup.select(
        "footer, .footer, #footer, .contact, #contact, .address, "
        "[itemtype*='PostalAddress']"
    ):
        section_text = section.get_text(separator=" ", strip=True)
        if _ADDR_RE.search(section_text) and len(section_text) < 500:
            addresses.append(section_text[:300])

    # ── Contact page URL ──────────────────────────────────────────────────
    contact_url = None
    for a_tag in soup.find_all("a", href=True):
        href_lower = a_tag["href"].lower()
        text_lower = a_tag.get_text(strip=True).lower()
        if "contact" in href_lower or "contact" in text_lower:
            contact_url = make_absolute_url(a_tag["href"], base_url)
            break

    return {
        "emails": list(emails_lower.values()) if emails_lower else None,
        "phones": phones if phones else None,
        "addresses": addresses if addresses else None,
        "contact_page_url": contact_url,
    }
