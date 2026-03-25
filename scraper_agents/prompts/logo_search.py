"""LogoAgent prompt — find logo URL via Gemini web search."""

LOGO_SEARCH_PROMPT = """\
Find the official logo image URL for {company_name} (website: {domain}).

Preferred sources (in order):
1. The company's own CDN or website (e.g., {domain}/logo.png, cdn.{domain}/logo.svg)
2. Brand resource/press page on their website
3. Wikipedia article thumbnail
4. Clearbit or similar logo API

Do NOT return:
- Social media profile pictures (they're cropped/circular)
- Favicon URLs (too small)
- Generic placeholder images

Return ONLY a JSON object:
{{
  "logo_urls": ["<url1>", "<url2>"],
  "source": "<where you found it>"
}}

Return ONLY valid JSON, no markdown fences.
"""
