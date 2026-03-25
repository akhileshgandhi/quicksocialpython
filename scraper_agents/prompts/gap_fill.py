"""WebSearchAgent prompt — fill data gaps via Google Search grounding."""

GAP_FILL_PROMPT = """\
I need to fill in missing information about {company_name} ({website_url}).

The following fields are missing or empty and need to be filled using web search:
{gap_fields}

Search the web for {company_name} and their website to find this information.

Return ONLY a JSON object with the fields you found. Use null for fields you could not find.
Example format:
{{
  "tagline": "<company tagline or null>",
  "brand_story": "<brief brand story or null>",
  "competitor_diff": "<what makes them different or null>",
  "contact_emails": ["<email>"],
  "contact_phones": ["<phone>"],
  "contact_addresses": ["<address>"],
  "products": [
    {{"name": "<product name>", "description": "<brief desc>", "category": "<category>"}}
  ],
  "services": [
    {{"name": "<service name>", "description": "<brief desc>", "category": "<category>"}}
  ]
}}

IMPORTANT:
- Only include fields that were listed as missing above.
- Only include FACTUAL information you can verify via search.
- Do NOT guess or fabricate data.
- Return ONLY valid JSON, no markdown fences.
"""

# Fields that can be searched (factual only, not analytical)
SEARCHABLE_GAP_FIELDS = {
    "contact_info.emails", "contact_info.phones", "contact_info.addresses",
    "tagline", "brand_story", "competitor_diff",
    "products", "services",
}
