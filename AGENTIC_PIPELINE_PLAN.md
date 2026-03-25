# Agentic Pipeline — Full Implementation Plan

> **Purpose:** Reference document for converting the current marketing post generation pipeline
> into a LangGraph-orchestrated agentic pipeline.
> Keep this open while working. Update status as phases are completed.

---

## Table of Contents

1. [What We Are Building](#1-what-we-are-building)
2. [Why Agentic — The Core Problem](#2-why-agentic--the-core-problem)
3. [Architecture Philosophy](#3-architecture-philosophy)
4. [New Folder Structure](#4-new-folder-structure)
5. [The State Object](#5-the-state-object)
6. [The Graph — Node Map](#6-the-graph--node-map)
7. [Node-by-Node Breakdown](#7-node-by-node-breakdown)
8. [Existing File Changes](#8-existing-file-changes)
9. [Phase 1 — Foundation](#9-phase-1--foundation)
10. [Phase 2 — Strategic Layer](#10-phase-2--strategic-layer)
11. [Phase 3 — Quality Loop](#11-phase-3--quality-loop)
12. [Phase 4 — Campaign Memory](#12-phase-4--campaign-memory)
13. [Quality Improvement Summary](#13-quality-improvement-summary)
14. [Dependencies](#14-dependencies)
15. [Implementation Checklist](#15-implementation-checklist)

---

## 1. What We Are Building

Converting the current FastAPI marketing pipeline from a **waterfall prompt chain** into a
**LangGraph-orchestrated agentic pipeline** with structured decision layers, typed state,
reflection on CV output, and self-correcting retry loops.

### What is NOT changing
- All FastAPI routes (`/smart-post`, `/create-campaign-advanced`, `/marketing-post-v2`)
- All utility functions in `utils.py` (CV pipeline, overlays, compositing)
- All prompt guard constants in `prompt_guards.py`
- All Pydantic models in `models.py`
- The Gemini API call pattern (same model, same config)
- The scraper pipeline (`scraper.py`) — entirely separate

### What IS changing
- **Orchestration layer:** LangGraph graph replaces inline pipeline logic
- **Decision making:** Design mode, narrative arc, and composition become typed state decisions
- **Quality control:** CV output is no longer thrown away — it gates retry decisions
- **Router functions:** Each router becomes a thin 20-line wrapper around `graph.ainvoke()`

---

## 2. Why Agentic — The Core Problem

### Current pipeline (simplified)

```
Request → Build Massive Prompt → Gemini Text → Gemini Image → CV → Overlay → Done
```

### The real limitations

| Problem | Impact |
|---------|--------|
| Design mode is a text hint buried inside prompts | Model ignores or misapplies it inconsistently |
| No narrative planning before carousel generation | 4 slides look similar, no story arc |
| Caption is generated without knowing visual plan | Image and caption describe different things |
| CV output (contrast, zone score) is computed then discarded | Bad-contrast images ship to users |
| No self-correction possible | One shot, whatever comes out goes to the user |
| Pipeline fails silently | Hard to pinpoint which step produced bad output |

### What agentic changes

```
Request
  → IntentAnalyzer (decides design mode + emotional trigger)
  → ContentPlanner (designs narrative arc before any generation)
  → CaptionGenerator (now mode-aware and arc-aware)
  → ImagePromptBuilder (reads caption + plan → builds focused prompt)
  → ImageGenerator (parallel)
  → CVAnalyzer (existing, unchanged)
  → TextOverlay (existing, unchanged)
  → QualityEvaluator (reads CV scores → approve or flag retry)
  → PromptRefiner (if retry: corrects prompt deterministically, no API)
  → [loop back to ImageGenerator for failed images only]
  → MetadataAssembler
  → Done
```

Nothing can say "this output does not match the original strategic intent" today.
The agentic pipeline can.

---

## 3. Architecture Philosophy

> **"Agentic does NOT mean more LLM calls everywhere."**
> It means: clear decision stages, typed state transitions,
> deterministic logic where possible, LLM only where necessary.

### Rules we follow

1. **LLM calls:** Only where human-level reasoning is needed (intent, narrative, captions, images)
2. **Deterministic nodes:** Prompt building, quality evaluation, retry refinement — zero API calls
3. **Retry cap:** Maximum 2 retries per image. Beyond that, best attempt ships.
4. **State is layered:** Strategic layer is frozen before content layer begins. Content layer is frozen before image layer begins.
5. **Existing code is sacred:** Every function in `utils.py` runs unchanged inside nodes.

### New vs existing LLM calls

| Call | Model | Existing or New | Phase |
|------|-------|-----------------|-------|
| IntentAnalyzer | gemini text | **NEW** | Phase 2 |
| ContentPlanner | gemini text | **NEW** | Phase 2 |
| CaptionGenerator | gemini text | Existing (wrapped) | Phase 1 |
| ImageGenerator | gemini image | Existing (wrapped) | Phase 1 |

**Only 2 new Gemini calls added total.** Everything else is deterministic.

---

## 4. New Folder Structure

```
Goals/
├── main.py                         ← minor: inject graph instance
├── smartpost.py                    ← thin wrapper only
├── campaign.py                     ← thin wrapper only
├── marketingpost.py                ← thin wrapper only
├── utils.py                        ← NO CHANGE
├── models.py                       ← NO CHANGE
├── prompt_guards.py                ← NO CHANGE
├── scraper.py                      ← NO CHANGE
│
└── graph/                          ← NEW FOLDER
    ├── __init__.py
    ├── state.py                    ← MarketingState TypedDict
    ├── marketing_graph.py          ← graph definition + compile
    │
    └── nodes/                      ← NEW FOLDER
        ├── __init__.py
        ├── router_node.py          ← branches on request_type
        ├── intent_analyzer.py      ← Gemini text call #1 (NEW logic)
        ├── content_planner.py      ← Gemini text call #2 (NEW logic)
        ├── caption_generator.py    ← existing _generate_smart_captions() wrapped
        ├── image_prompt_builder.py ← deterministic prompt builder (NEW logic)
        ├── image_generator.py      ← existing Gemini image call wrapped
        ├── cv_analyzer.py          ← existing analyze_and_layout() wrapped
        ├── text_overlay_node.py    ← existing overlay + composite wrapped
        ├── quality_evaluator.py    ← deterministic CV score reader (NEW logic)
        ├── prompt_refiner.py       ← deterministic string modifier (NEW logic)
        └── metadata_assembler.py   ← existing save + build_layered_data wrapped
```

---

## 5. The State Object

**File:** `graph/state.py`

The single most important design decision. Every node reads from and writes to this.
Sections are layered — upstream sections are not rewritten by downstream nodes.

```python
from typing import TypedDict, Optional, List, Dict, Any

class MarketingState(TypedDict):

    # ── RAW INPUT ──────────────────────────────────────────────────────
    # Filled at entry. Never modified after.
    request_type: str           # "smartpost" | "campaign" | "single"
    request_meta: Dict          # platform, num_posts, content_mode, media_type,
                                # posting_goal, num_slides
    brand_data: Dict            # company_name, description, colors, voice,
                                # tagline, website, logo_bytes, logo_url
    user_constraints: Dict      # custom_prompt, reference_images, posting_goal

    # ── STRATEGIC LAYER ────────────────────────────────────────────────
    # Filled by IntentAnalyzerNode. Frozen before ContentPlannerNode runs.
    intent: Dict                # {
                                #   design_mode: "PHOTO_OVERLAY"|"GRAPHIC_LAYOUT"|
                                #                "SPLIT_LAYOUT"|"FRAMED_HERO",
                                #   emotional_trigger: "aspiration"|"trust"|
                                #                      "excitement"|"urgency"|"joy",
                                #   goal_context: {primary_focus, visual_style, tone},
                                #   festival_context: null | {name, greeting, themes[]}
                                # }

    # Filled by ContentPlannerNode. Frozen before CaptionGeneratorNode runs.
    narrative_plan: Dict        # {
                                #   arc_description: str,
                                #   slides: [
                                #     {slide_purpose, visual_brief, hero_element,
                                #      text_zone_direction}
                                #   ]
                                # }

    # Filled by ImagePromptBuilderNode. One plan per image.
    composition_plan: List[Dict]  # [{preferred_zone, gemini_directive,
                                  #   scoring_positions}]

    # ── CONTENT LAYER ──────────────────────────────────────────────────
    # Filled by CaptionGeneratorNode.
    captions: List[Dict]        # [{caption, hashtags, variation_label}]
    display_texts: List[str]    # per-image validated display text

    # Filled by ImagePromptBuilderNode.
    image_prompts: List[str]    # one complete prompt per image

    # ── IMAGE LAYER ────────────────────────────────────────────────────
    # Filled by ImageGeneratorNode.
    raw_images: List[Optional[bytes]]

    # Filled by CVAnalyzerNode.
    cv_data: List[Optional[Dict]]   # full analyze_and_layout() output per image
                                    # includes: primary_zone, text_blocks,
                                    #           wcag_contrast, gradient_direction

    # Filled by TextOverlayNode.
    final_images: List[Optional[bytes]]
    layered_data: List[Optional[Dict]]

    # ── QUALITY LAYER ──────────────────────────────────────────────────
    # Filled by QualityEvaluatorNode.
    evaluation: List[Dict]      # per image: {contrast_ok, zone_ok, score_ok,
                                #             overall_pass, failures: []}
    retry_targets: List[int]    # indexes of images that failed quality check
    retry_count: int            # incremented by PromptRefinerNode; capped at 2

    # ── OUTPUT ─────────────────────────────────────────────────────────
    save_results: List[Dict]
    final_response: Dict
    errors: List[str]
```

### Why layered separation matters

If a bad image ships, you inspect in order:
1. `intent` → was design_mode correct?
2. `narrative_plan` → was the visual brief specific enough?
3. `image_prompts` → was the prompt built correctly?
4. `cv_data` → what did the analyzer see?
5. `evaluation` → did it fail the quality gate? Why?

You know exactly which layer produced the wrong input.

---

## 6. The Graph — Node Map

```
START
  │
  ▼
RouterNode
  │ branches on request_type
  ├─ "smartpost"  ──┐
  ├─ "campaign"   ──┤
  └─ "single"     ──┘
                    │
                    ▼
             IntentAnalyzerNode          ← Gemini text call #1
             (design_mode, emotional_trigger, goal_context, festival_context)
                    │
                    ▼
             ContentPlannerNode          ← Gemini text call #2
             (narrative arc, visual_briefs[], slide_purposes[])
                    │
                    ▼
             CaptionGeneratorNode        ← Gemini text call (existing)
             (captions[], display_texts[])
                    │
                    ▼
             ImagePromptBuilderNode      ← deterministic, no API
             (image_prompts[] — one per image, mode-aware, brief-aware)
                    │
                    ▼
    ┌───────── PARALLEL MAP ─────────────┐
    │   (one branch per image_prompt)    │
    │                                    │
    │   ImageGeneratorNode               │  ← Gemini image call (existing)
    │         │                          │
    │   CVAnalyzerNode                   │  ← analyze_and_layout() (existing)
    │         │                          │
    │   TextOverlayNode                  │  ← overlay + composite (existing)
    │                                    │
    └──────────── JOIN ──────────────────┘
                    │
                    ▼
             QualityEvaluatorNode        ← deterministic, reads cv_data
             (scores each image, populates retry_targets[])
                    │
          ┌─────────┴──────────┐
          │                    │
   [retry_targets              │
    non-empty AND              │
    retry_count < 2]    [all pass OR max retries]
          │                    │
          ▼                    ▼
   PromptRefinerNode    MetadataAssemblerNode   ← save + build response (existing)
   (modifies prompts           │
    for failed indexes)        ▼
          │                   END
          ▼
   ImageGeneratorNode
   (retry failed indexes only)
          │
   CVAnalyzerNode
   TextOverlayNode
          │
          └──── back to QualityEvaluatorNode
```

### Conditional edge logic

```python
def should_retry(state: MarketingState) -> str:
    if state["retry_targets"] and state["retry_count"] < 2:
        return "refine"      # → PromptRefinerNode
    return "assemble"        # → MetadataAssemblerNode
```

---

## 7. Node-by-Node Breakdown

### RouterNode
- **File:** `graph/nodes/router_node.py`
- **Type:** Deterministic
- **Input:** `request_type` from state
- **What it does:** Sets up sub-graph routing. Different request types share 90% of nodes
  but have minor differences (campaign uses semaphore, smartpost has carousel logic).
- **Output:** Routes to IntentAnalyzerNode

---

### IntentAnalyzerNode  *(NEW — Phase 2)*
- **File:** `graph/nodes/intent_analyzer.py`
- **Type:** Gemini text call
- **Input:** `brand_data`, `request_meta`, `user_constraints`
- **What it does:**
  - Decides `design_mode` (PHOTO_OVERLAY / GRAPHIC_LAYOUT / SPLIT_LAYOUT / FRAMED_HERO)
  - Extracts `emotional_trigger` (aspiration / trust / excitement / urgency / joy)
  - Builds `goal_context` (primary_focus, visual_style, tone)
  - Detects `festival_context` if posting_goal == festival_event
- **Replaces:** `_get_posting_goal_context()` + manual design mode hints in prompts
- **Why it matters:**
  - `design_mode` becomes a typed state value that ALL downstream nodes branch on
  - Without this, GRAPHIC_LAYOUT and PHOTO_OVERLAY get nearly identical prompts

**Prompt structure:**
```
Given brand context + platform + goal + custom prompt:

Analyze the strategic intent and respond as JSON:
{
  "design_mode": "PHOTO_OVERLAY" | "GRAPHIC_LAYOUT" | "SPLIT_LAYOUT" | "FRAMED_HERO",
  "emotional_trigger": "aspiration" | "trust" | "excitement" | "urgency" | "joy",
  "goal_context": {
    "primary_focus": "...",
    "visual_style": "...",
    "tone": "..."
  },
  "festival_context": null | { "name": "...", "greeting": "...", "themes": [...] }
}
```

---

### ContentPlannerNode  *(NEW — Phase 2)*
- **File:** `graph/nodes/content_planner.py`
- **Type:** Gemini text call
- **Input:** `intent`, `brand_data`, `request_meta` (num_slides, media_type)
- **What it does:**
  - Designs visual narrative before any generation
  - For single post: focused visual brief with scene intent
  - For carousel: full story arc (tension → reveal → proof → CTA)
  - For A/B: 3 distinct creative angles for the same message
- **Currently absent** — this logic does not exist anywhere in the pipeline

**Prompt structure:**
```
Given the strategic intent above and {num_slides} images to generate:

Design the visual narrative. For each slide define:
- slide_purpose: what this specific slide communicates
- visual_brief: specific scene/composition description
- hero_element: what dominates the frame (person/product/abstract/environment)
- text_zone_direction: where text will sit (left/right/bottom/top/center)

Respond as JSON:
{
  "arc": "brief arc description",
  "slides": [
    {
      "slide_number": 1,
      "slide_purpose": "...",
      "visual_brief": "...",
      "hero_element": "...",
      "text_zone_direction": "..."
    }
  ]
}
```

**Before vs after — carousel:**
| Before | After |
|--------|-------|
| "Slide 2 of 4, continue the campaign theme" | "Slide 2: product reveal — hero shot of product against clean background, text zone right, this is the solution moment" |
| 4 images with same generic context | 4 images each with unique, specific purpose |
| No visual story | Customer journey across slides |

---

### CaptionGeneratorNode
- **File:** `graph/nodes/caption_generator.py`
- **Type:** Gemini text call (existing logic)
- **Input:** `intent`, `narrative_plan`, `brand_data`, `request_meta`
- **What it does:**
  - Same as existing `_generate_smart_captions()` (smartpost) and
    `generate_caption_and_hashtags()` (campaign/single)
  - **Now mode-aware:** prompt references `design_mode` from intent
  - **Now arc-aware:** caption for slide 2 references slide 2's `slide_purpose`
- **Changes from current:** Structural wrap + prompt enriched with intent + narrative context
- **Output:** `captions[]`, `display_texts[]`

---

### ImagePromptBuilderNode  *(NEW logic — Phase 2)*
- **File:** `graph/nodes/image_prompt_builder.py`
- **Type:** Deterministic, no API
- **Input:** `intent`, `narrative_plan`, `captions`, `display_texts`, `brand_data`, `composition_plan`
- **What it does:**
  - Builds one complete image prompt per image
  - Reads `design_mode` → selects appropriate prompt template
  - Reads `visual_brief[i]` → core scene description for this slide
  - Reads `display_text[i]` → includes spatial hint for text zone
  - Reads `emotional_trigger` → injects mood/lighting direction
  - Applies `REALISM_ENFORCER` + `NEGATIVE_PROMPT` + `MINIMAL_TEXT_DIRECTIVE` from guards
    based on the active `design_mode`
- **Output:** `image_prompts[]` — one complete, inspectable prompt per image
- **Why this matters:** Currently the prompt is built inline inside an async generation
  function — untestable, not inspectable. Moving it to a dedicated node makes it
  a pure function you can test, log, and debug independently.

---

### ImageGeneratorNode
- **File:** `graph/nodes/image_generator.py`
- **Type:** Gemini image calls (existing logic)
- **Input:** `image_prompts[]`, `brand_data` (reference images), `request_meta`
- **What it does:**
  - Same parallel `asyncio.gather()` pattern as current pipeline
  - Reads prompt from `state["image_prompts"][i]` instead of building inline
  - Campaign: semaphore(5) for max 5 concurrent calls
  - Returns raw image bytes per image
- **Changes from current:** Reads prompt from state instead of building it internally

---

### CVAnalyzerNode
- **File:** `graph/nodes/cv_analyzer.py`
- **Type:** Deterministic, no API (existing functions)
- **Input:** `raw_images[]`, `display_texts[]`, `brand_data`
- **What it does:**
  - Calls existing `analyze_and_layout()` for each image
  - Calls existing `prepare_text_space()`
  - **Crucially:** saves full CV output to state (currently this data is used once and lost)
- **Output:** `cv_data[]` — full analysis per image including contrast scores, zone info,
  text blocks, WCAG ratios, composite scores
- **Zero logic changes** — same functions, but output is now preserved in state

---

### TextOverlayNode
- **File:** `graph/nodes/text_overlay_node.py`
- **Type:** Deterministic, no API (existing functions)
- **Input:** `raw_images[]`, `cv_data[]`, `brand_data`
- **What it does:**
  - Calls existing `_render_adaptive_text_overlay()`
  - Calls existing `_composite_text_overlay()`
  - Calls existing `_render_logo_overlay()` if logo present
- **Output:** `final_images[]`, `layered_data[]`
- **Zero logic changes** — pure wrap

---

### QualityEvaluatorNode  *(NEW — Phase 3)*
- **File:** `graph/nodes/quality_evaluator.py`
- **Type:** Deterministic, no API
- **Input:** `cv_data[]`, `brand_data` (brand colors)
- **What it does:**

```python
for i, data in enumerate(state["cv_data"]):
    # All these values already exist in cv_data — computed by existing CV pipeline
    contrast_ratio  = data["wcag_contrast"]                  # from compute_wcag_colors()
    zone_complexity = data["primary_zone"]["complexity"]     # "simple"|"moderate"|"busy"
    zone_score      = data["primary_zone"]["composite_score"] # from find_best_text_region()

    failures = []
    if contrast_ratio < 4.5:           failures.append("contrast_low")
    if zone_complexity == "busy":      failures.append("zone_busy")
    if zone_score < 0.35:              failures.append("score_low")

    evaluation[i] = {
        "contrast_ok": contrast_ratio >= 4.5,
        "zone_ok":     zone_complexity != "busy",
        "score_ok":    zone_score >= 0.35,
        "overall_pass": len(failures) == 0,
        "failures": failures
    }
    if failures:
        retry_targets.append(i)
```

- **The key insight:** You already compute WCAG contrast ratios, zone complexity, and
  composite scores inside your existing CV pipeline. Today that data is logged and
  discarded. This node just acts on it.
- **No additional computation. No API calls. Zero cost.**

---

### PromptRefinerNode  *(NEW — Phase 3)*
- **File:** `graph/nodes/prompt_refiner.py`
- **Type:** Deterministic, no API
- **Input:** `image_prompts[]`, `evaluation[]`, `cv_data[]`, `retry_targets[]`
- **What it does:** For each failed image, appends specific correction strings:

```python
REFINEMENT_MAP = {
    "contrast_low":  ", soft diffused lighting on {zone}, clear negative space, "
                     "minimal visual noise in text zone area",
    "zone_busy":     ", {zone_direction} side of frame is clean and uncluttered, "
                     "simple low-detail background in text zone",
    "score_low":     ", strong clear separation between subject and background, "
                     "subject is well-isolated",
    "brand_color_miss": ", background subtly incorporates warm {hex} as ambient "
                        "color tone"
}

for i in state["retry_targets"]:
    zone = state["cv_data"][i]["primary_zone"]["direction"]   # "left"|"right"|"bottom"
    for failure in state["evaluation"][i]["failures"]:
        addition = REFINEMENT_MAP[failure].format(zone=zone, ...)
        state["image_prompts"][i] += addition

state["retry_count"] += 1
```

- **Must NOT call Gemini.** Corrections are deterministic string operations.
- Routes back to `ImageGeneratorNode` for retry targets only (not all images).

---

### MetadataAssemblerNode
- **File:** `graph/nodes/metadata_assembler.py`
- **Type:** Deterministic (existing functions)
- **Input:** `final_images[]`, `cv_data[]`, `captions[]`, `layered_data[]`, `brand_data`
- **What it does:**
  - Calls existing `_save_smart_post_image()` / `save_campaign_image()`
  - Calls existing `_build_layered_data()`
  - Saves `post_metadata.json`
  - Builds `final_response` dict matching existing Pydantic response models
- **Zero logic changes** — pure wrap

---

## 8. Existing File Changes

### `main.py`
**Change:** Create graph instance and inject into routers.

```python
# ADD after model initialization:
from graph.marketing_graph import create_marketing_graph
marketing_graph = create_marketing_graph(
    client=gemini_client,
    text_model=gemini_model,
    image_model=image_model,
    storage_dir=storage_dir,
    yolo_model=yolo_model
)

# MODIFY router creation to pass graph:
app.include_router(create_campaign_router(marketing_graph))
app.include_router(create_smartpost_router(marketing_graph))
app.include_router(create_marketingpost_router(marketing_graph))
```

---

### `smartpost.py`
**Change:** Router function becomes a thin 20-line wrapper.

```python
# REMOVE: _generate_smart_captions(), _generate_single_smart_image()
#         (these become graph nodes)

# KEEP:   _save_smart_post_image() → moves to metadata_assembler node
#         _get_posting_goal_context() → moves to intent_analyzer node

# REWRITE create_smart_post() to:
async def create_smart_post(graph, ...form fields...):
    state = {
        "request_type": "smartpost",
        "brand_data": { company_name, description, colors, logo_bytes, ... },
        "request_meta": { platform, content_mode, media_type, posting_goal, ... },
        "user_constraints": { custom_prompt, ... },
        # all other state fields initialized to empty defaults
    }
    result = await graph.ainvoke(state)
    return SmartPostResponse(**result["final_response"])
```

---

### `campaign.py`
**Change:** Router function becomes a thin wrapper.

```python
# REMOVE: _generate_single_post()
#         (becomes graph nodes)

# KEEP:   Distribution math (product/service/brand percentages) → stays in router
#         Queue building logic → stays in router, passed via state

# REWRITE create_campaign_advanced() to:
async def create_campaign_advanced(graph, ...form fields...):
    # Parse products, services, build generation_queue (existing logic stays here)
    state = {
        "request_type": "campaign",
        "brand_data": { ... },
        "request_meta": { generation_queue, platforms, content_strategy, ... },
        ...
    }
    result = await graph.ainvoke(state)
    return CampaignResponse(**result["final_response"])
```

---

### `marketingpost.py`
**Change:** Router function becomes a thin wrapper.

```python
# REMOVE: validate_enhance_and_generate_caption(), build_complete_image_prompt()
#         (become graph nodes)

# REWRITE generate_marketing_post_v2() to thin wrapper
```

---

### Files with zero changes
| File | Reason |
|------|--------|
| `utils.py` | All functions called inside nodes, not changed |
| `models.py` | All Pydantic models still used for I/O validation |
| `prompt_guards.py` | Guards imported and applied inside ImagePromptBuilderNode |
| `scraper.py` | Entirely separate pipeline, not touched |

---

## 9. Phase 1 — Foundation

**Goal:** Get graph running. Output must be **identical** to today.

### Steps

1. **Install LangGraph**
   ```bash
   pip install langgraph>=0.2.0
   ```

2. **Create `graph/state.py`**
   - Define `MarketingState` TypedDict with all fields
   - Add helper function `create_initial_state(request_type, brand_data, ...)`

3. **Create node files (thin wrappers)**
   - Each node calls existing functions and reads/writes state
   - No new logic — pure structural migration
   - Order: `caption_generator` → `image_generator` → `cv_analyzer` →
     `text_overlay_node` → `metadata_assembler`

4. **Create `graph/marketing_graph.py`**
   - Define graph with `StateGraph(MarketingState)`
   - Add all nodes with `graph.add_node()`
   - Add edges with `graph.add_edge()`
   - Compile with `graph.compile()`

5. **Create `graph/nodes/router_node.py`**
   - Branches on `request_type`

6. **Modify router files** (`smartpost.py`, `campaign.py`, `marketingpost.py`)
   - Replace pipeline logic with `graph.ainvoke(state)`
   - Keep form parsing + response building

7. **Modify `main.py`**
   - Create graph instance
   - Inject into routers

8. **Test: all 3 endpoints return identical output**

### Success criteria for Phase 1
- `/smart-post` → same response as before
- `/create-campaign-advanced` → same response as before
- `/marketing-post-v2` → same response as before
- No regression in output quality

---

## 10. Phase 2 — Strategic Layer

**Goal:** Pipeline thinks before it generates. Visible improvement in output quality.

### Steps

1. **Build `IntentAnalyzerNode`**
   - Gemini text call with structured JSON output
   - Parse response into `state["intent"]`
   - Handle all 3 request types (smartpost/campaign/single)
   - Fallback: if Gemini fails, build intent from request_meta deterministically

2. **Build `ContentPlannerNode`**
   - Gemini text call with narrative arc output
   - Parse into `state["narrative_plan"]`
   - Handles: single post, carousel (4 slides), A/B (3 variations)
   - Fallback: generic slide purposes if Gemini fails

3. **Build `ImagePromptBuilderNode`**
   - Pure deterministic function
   - Template selector based on `design_mode`
   - Injects `visual_brief[i]` from narrative_plan into each image prompt
   - Applies guards from `prompt_guards.py` per mode
   - Saves built prompts to `state["image_prompts"]`

4. **Update `CaptionGeneratorNode`**
   - Add intent + narrative context to caption prompt
   - Caption for slide 2 now references slide 2's `slide_purpose`

5. **Wire new nodes into graph**
   - Insert before existing caption generator: `intent_analyzer → content_planner`
   - Insert after caption generator: `image_prompt_builder`

6. **Test and compare output**
   - Run same request through old vs new pipeline
   - Compare carousel coherence visually

### What improves after Phase 2
- **Carousel:** Each slide has a specific visual purpose (planned before generation)
- **Single post:** Image and caption describe the same thing
- **Design mode:** Typed decision — GRAPHIC_LAYOUT gets poster-style prompt,
  PHOTO_OVERLAY gets photographic scene construction prompt
- **Festival posts:** Festival context resolved at intent stage, consistently applied

---

## 11. Phase 3 — Quality Loop

**Goal:** Self-correct before delivery. Catch contrast failures automatically.

### Steps

1. **Verify cv_data is fully preserved in state**
   - Confirm `CVAnalyzerNode` saves complete `analyze_and_layout()` output
   - Required fields: `wcag_contrast`, `primary_zone.complexity`,
     `primary_zone.composite_score`, `primary_zone.direction`

2. **Build `QualityEvaluatorNode`**
   - Read `cv_data[i]` per image
   - Apply thresholds: contrast ≥ 4.5 (WCAG AA), zone != "busy", score ≥ 0.35
   - Populate `evaluation[]` and `retry_targets[]`

3. **Build `PromptRefinerNode`**
   - Define `REFINEMENT_MAP` dict (failure type → correction string template)
   - Apply corrections to `image_prompts[i]` for each retry target
   - Increment `retry_count`
   - Route: only retry_target indexes re-generated (not all images)

4. **Wire conditional edge**
   ```python
   graph.add_conditional_edges(
       "quality_evaluator",
       should_retry,    # checks retry_targets + retry_count
       {
           "refine": "prompt_refiner",
           "assemble": "metadata_assembler"
       }
   )
   graph.add_edge("prompt_refiner", "image_generator")  # loops back
   ```

5. **Tune thresholds**
   - Run 20+ test requests, measure retry rate
   - Target: ~20–30% of images trigger 1 retry, <5% trigger 2nd retry
   - Adjust thresholds if retry rate is too high (too aggressive) or too low (too lenient)

### What improves after Phase 3
- ~30–40% of contrast failures caught and corrected before delivery
- "Busy" zone images get a second generation attempt with spatial correction
- WCAG AA compliance rate increases significantly
- Users never see failed attempts — only approved version ships

### Latency impact
- No retry (most requests): +50ms (deterministic evaluation only)
- 1 retry: +50ms + 2–4s (re-generate failed images only)
- 2 retries (worst case): +50ms + 4–8s total added

---

## 12. Phase 4 — Campaign Memory

**Goal:** Visual diversity across a 20-post campaign.

### Steps

1. **Add visual_memory to MarketingState**
   ```python
   visual_memory: Dict  # {
                        #   used_design_modes: List[str],
                        #   used_hero_styles: List[str],
                        #   used_compositions: List[str],
                        #   used_color_temperatures: List[str]
                        # }
   ```

2. **Build `VisualMemoryNode`**
   - Runs between `ContentPlannerNode` and `ImagePromptBuilderNode`
   - Campaign only (skip for smartpost/single)
   - Reads `visual_memory` state
   - Enforces variety rules:
     ```
     If last 3 posts used PHOTO_OVERLAY  → override to GRAPHIC_LAYOUT
     If last 2 hero_styles were "person" → override to "product" or "environment"
     If last 3 compositions were left    → override to right or center
     ```
   - Updates `narrative_plan` for current post to reflect overrides
   - Appends current post's choices back to `visual_memory`

3. **Wire into campaign sub-graph only**
   - `content_planner → visual_memory → image_prompt_builder` (campaign)
   - `content_planner → image_prompt_builder` (smartpost / single)

### What improves after Phase 4
- A 20-post campaign will have natural variety across all 4 design modes
- No repeated compositions back-to-back
- Visual rhythm across the campaign — variety without chaos

---

## 13. Quality Improvement Summary

| Phase | Latency Added | Output Quality Gain |
|-------|--------------|---------------------|
| **Phase 1** — Wrap existing code | ~0ms (identical execution) | 0% change in output quality. Pipeline becomes inspectable. Failures are now attributed to specific nodes. Foundation for all future phases. |
| **Phase 2** — IntentAnalyzer + ContentPlanner | +400–600ms (2 text calls) | ~25–35% improvement in carousel coherence. Slides tell a story instead of being 4 near-identical images. ~15–20% improvement in single post image-caption alignment. Design mode is an actual typed decision. |
| **Phase 3** — QualityEvaluator + Retry | +50ms no retry / +2–8s with retry | ~30–40% reduction in contrast failures shipping to users. WCAG AA compliance improves significantly. Self-correcting — bad attempts don't reach the user. |
| **Phase 4** — Campaign Visual Memory | ~0ms (state reads only) | ~15–20% improvement in campaign visual variety. No repeated design modes or compositions in sequence. Campaign feels curated, not repetitive. |

### Net additional Gemini API calls
| Call | Phase | Cost |
|------|-------|------|
| IntentAnalyzerNode | Phase 2 | 1 text call per request |
| ContentPlannerNode | Phase 2 | 1 text call per request |
| PromptRefinerNode retry | Phase 3 | 0 (deterministic) + 1 image call per failed image (conditional) |
| VisualMemoryNode | Phase 4 | 0 (deterministic) |

**Total guaranteed new calls: 2 text calls per request.**
Retry image calls: conditional, 0–2 per failed image.

---

## 14. Dependencies

### Install
```bash
pip install langgraph>=0.2.0
```

LangGraph installs `langchain-core` as a dependency but you will not import from it directly.
All your existing code (Gemini client, Pydantic models, CV pipeline) stays exactly as-is.
LangGraph only manages graph execution, state passing, and conditional routing.

### Requirements entry
```
langgraph>=0.2.0
```

### What you do NOT need
- LangChain (not required for LangGraph with custom models)
- LangSmith (optional tracing — useful in Phase 3 for debugging retries)
- Any new Gemini SDK version (existing client works as-is)

---

## 15. Implementation Checklist

### Phase 1 — Foundation
- [ ] Install langgraph
- [ ] Create `graph/` folder and `__init__.py`
- [ ] Create `graph/state.py` with `MarketingState` + `create_initial_state()`
- [ ] Create `graph/nodes/__init__.py`
- [ ] Create `graph/nodes/router_node.py`
- [ ] Create `graph/nodes/caption_generator.py` (wrap existing logic)
- [ ] Create `graph/nodes/image_generator.py` (wrap existing logic)
- [ ] Create `graph/nodes/cv_analyzer.py` (wrap existing logic)
- [ ] Create `graph/nodes/text_overlay_node.py` (wrap existing logic)
- [ ] Create `graph/nodes/metadata_assembler.py` (wrap existing logic)
- [ ] Create `graph/marketing_graph.py` (define + compile graph)
- [ ] Modify `smartpost.py` → thin wrapper
- [ ] Modify `campaign.py` → thin wrapper
- [ ] Modify `marketingpost.py` → thin wrapper
- [ ] Modify `main.py` → inject graph
- [ ] Test: all 3 endpoints return identical output

### Phase 2 — Strategic Layer
- [ ] Create `graph/nodes/intent_analyzer.py`
- [ ] Create `graph/nodes/content_planner.py`
- [ ] Create `graph/nodes/image_prompt_builder.py`
- [ ] Update `graph/nodes/caption_generator.py` to use intent + narrative context
- [ ] Wire new nodes into graph
- [ ] Test carousel coherence (before vs after comparison)
- [ ] Test single post image-caption alignment

### Phase 3 — Quality Loop
- [ ] Verify cv_data fields (wcag_contrast, zone complexity, composite_score) are in state
- [ ] Create `graph/nodes/quality_evaluator.py`
- [ ] Create `graph/nodes/prompt_refiner.py` with `REFINEMENT_MAP`
- [ ] Wire conditional edge (should_retry function)
- [ ] Wire retry loop (prompt_refiner → image_generator)
- [ ] Test: force a contrast-failing scenario, verify retry triggers
- [ ] Tune thresholds based on 20+ test runs

### Phase 4 — Campaign Memory
- [ ] Add `visual_memory` field to `MarketingState`
- [ ] Create `graph/nodes/visual_memory_node.py`
- [ ] Wire into campaign sub-graph only
- [ ] Test: 20-post campaign, verify design mode distribution

---

*Document version: 1.0*
*Created: Based on full pipeline analysis of smartpost.py, campaign.py, marketingpost.py, utils.py*
*Last updated: Start of implementation*
