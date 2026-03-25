"""VisualAgent prompt — verify brand colors via Gemini."""

COLOR_VERIFICATION_PROMPT = """\
What are the official brand colors of {company_name}?

Return ONLY a JSON object:
{{
  "primary_color": "<hex code or null>",
  "secondary_color": "<hex code or null>",
  "confidence": <0.0-1.0>
}}

If you don't know the brand's official colors, return confidence 0.0 and null for both.
Return ONLY valid JSON, no markdown fences.
"""

SCREENSHOT_COLOR_PROMPT = """\
Analyze this website screenshot and identify the brand's primary and secondary colors.
Ignore white/gray backgrounds, black text, and any star-rating gold (#FFD700).
Focus on: header/nav background color, CTA button colors, accent colors, logo colors.

Company name: {company_name}

Return ONLY a JSON object:
{{
  "primary_color": "<hex code>",
  "secondary_color": "<hex code or null>"
}}

Return ONLY valid JSON, no markdown fences.
"""
