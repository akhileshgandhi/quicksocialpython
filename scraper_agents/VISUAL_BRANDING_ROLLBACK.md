# Visual branding API — rollback notes

## Current implementation (three string fields)

**Date:** 2026-04-08 (updated)

### `SmartScrapeResponse.visual_branding` (agentic `/smart-scrape-v2`)

- **`primary_color`**: `string | null` — hex `#RRGGBB` from `brand_palette["primary"]` (HSL `resolve_brand_palette`). Normalized; if missing, orchestrator uses fallback `#1A1A2E`.
- **`secondary_color`**: `string | null` — from `brand_palette["secondary"]`, fallback `#FFFFFF`.
- **`accent_color`**: `string | null` — from `brand_palette["accent"]`, fallback `#4F46E5`.
- **`headline_text_color`**: WCAG contrast vs **primary** (string).
- **Structured palette** remains in `color_audit` and `scrape_metadata.json` (`brand_palette` / `color_audit`).

### Code touchpoints

- `models.py` — `VisualBranding` (`primary_color`, `secondary_color`, `accent_color` as `Optional[str]`)
- `scraper_agents/orchestrator.py` — `_normalize_hex_one`, `_visual_branding_hex_triple`, `_assemble_response`
- Legacy `scraper.py` smart-scrape path — strings from Gemini + scraper heuristics (`accent_color` from analysis when present)

---

## Rollback A — HSL triple as a single list on `primary_color`

**Previous contract:** `primary_color` was `string[]` with up to three entries `[primary, secondary, accent]` only (no separate keys).

### Steps

1. In `models.py`, set `primary_color: Optional[List[str]]` and `secondary_color` / `accent_color` reserved (`null`).
2. In `orchestrator.py`, replace `_visual_branding_hex_triple` usage with a list builder, e.g.:

```python
def _frontend_primary_color_list(state: ScrapeState) -> List[str]:
    bp = state.brand_palette or {}
    candidates: List[str] = []
    for key in ("primary", "secondary", "accent"):
        v = bp.get(key)
        if v and isinstance(v, str):
            candidates.append(v)
    merged = _normalize_hex_color_list(candidates, max_colors=3)
    if merged:
        return merged
    return _normalize_hex_color_list(["#1A1A2E", "#FFFFFF", "#4F46E5"], max_colors=3)
```

3. In `_assemble_response`, set `primary_color=primary_color_list or None`, `secondary_color=None`, `accent_color=None`, and `primary_for_contrast = primary_color_list[0] if primary_color_list else "#1A1A2E"`.
4. Fix `scraper.py` `VisualBranding(...)` to match (e.g. list for agentic parity if you unify paths).
5. Run `pytest tests/`.

---

## Rollback B — merged discovery swatches (max 24) on `primary_color`

**Older contract (2026-04-07):** `primary_color` was a long ordered list: `colors_found` + visual-agent list + all five `brand_palette` keys.

Paste the body of `_frontend_primary_color_list` from git history (see Rollback A in older commits) or reconstruct from:

- `state.colors_found`, `state.primary_color`, then keys `primary`, `secondary`, `accent`, `background`, `text` from `brand_palette`, `max_colors=24`.

---

## Rollback C — original three separate fields without orchestrator fallbacks

If APIs must return `null` when a palette slot is absent instead of `#1A1A2E` / `#FFFFFF` / `#4F46E5`, change `_visual_branding_hex_triple` to return `Optional[str]` per slot and pass through `None` when `brand_palette` lacks that key (still normalize when present).

---

## Git

Revert the commit that introduced the current shape, or apply the steps above manually.
