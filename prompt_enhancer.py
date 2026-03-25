"""
Prompt Enhancer — takes a rough user idea and generates 3 ready-to-use creative directions
for QuikSocial's AI marketing post generator.

User picks one option and its scene_description is passed directly as:
  - custom_prompt → /create-campaign-advanced
  - custom_prompt → /smart-post
"""
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Form, HTTPException

from models import PromptEnhancerResponse, PromptOption

logger = logging.getLogger("quicksocial.prompt_enhancer")

# Posting goal → plain-English guidance injected into the system prompt
_GOAL_GUIDANCE = {
    "product_launch":   "The post is announcing a new product. Highlight novelty, excitement, and desire.",
    "brand_awareness":  "The post builds brand recognition. Focus on brand story, values, and emotional connection.",
    "promotion":        "The post drives a sale or offer. Communicate urgency, value, and clear benefit.",
    "festival":         "The post celebrates a festival or event. Capture the festive spirit and cultural warmth.",
    "engagement":       "The post sparks interaction. Use curiosity, relatability, or a bold visual hook.",
    "carousel":         "This is for a multi-slide carousel. Each option should suggest a strong visual narrative thread that works across slides.",
    "campaign":         "This is for a multi-post campaign. Each option should feel like a campaign concept that can produce 4-8 consistent images.",
}


def create_prompt_enhancer_router(gemini_client, gemini_model):
    router = APIRouter(tags=["Prompt Enhancer"])

    @router.post("/enhance-prompt", response_model=PromptEnhancerResponse)
    async def enhance_prompt(
        user_prompt: str = Form(..., description="Your rough idea — can be as vague as 'coffee shop morning vibes' or as specific as you like"),
        company_name: Optional[str] = Form(None, description="Company / brand name"),
        company_description: Optional[str] = Form(None, description="What the company does or sells (1-2 sentences)"),
        brand_voice: Optional[str] = Form(None, description="Brand personality (e.g. 'luxury', 'playful', 'bold', 'minimal', 'corporate')"),
        platform: Optional[str] = Form(None, description="Target platform: instagram, facebook, linkedin, twitter"),
        posting_goal: Optional[str] = Form(None, description="What this post is for: product_launch, brand_awareness, promotion, festival, engagement, carousel, campaign"),
    ):
        """
        Transform a rough user idea into 3 distinct, ready-to-use creative directions
        for QuikSocial's AI marketing post generator.

        Each option's `scene_description` is a concise, direct creative brief that can be
        pasted directly as `image_prompt` into /create-campaign-advanced or
        `custom_prompt` into /smart-post — no editing needed.
        """
        start_time = time.time()

        logger.info("=" * 60)
        logger.info(f"[ENHANCE] New request received")
        logger.info(f"[ENHANCE] User prompt: '{user_prompt}'")
        logger.info(f"[ENHANCE] Company: {company_name or '(none)'}")
        logger.info(f"[ENHANCE] Description: {company_description[:80] + '...' if company_description and len(company_description) > 80 else company_description or '(none)'}")
        logger.info(f"[ENHANCE] Brand voice: {brand_voice or '(none)'}")
        logger.info(f"[ENHANCE] Platform: {platform or '(none)'}")
        logger.info(f"[ENHANCE] Posting goal: {posting_goal or '(none)'}")

        # ── Brand context block ──────────────────────────────────────────────
        brand_section = ""
        if company_name or company_description or brand_voice:
            parts = []
            if company_name:
                parts.append(f"Brand: {company_name}")
            if company_description:
                parts.append(f"What they do: {company_description[:200]}")
            if brand_voice:
                parts.append(f"Brand personality: {brand_voice}")
            brand_section = "\n\nBRAND CONTEXT:\n" + "\n".join(parts)
            logger.info(f"[ENHANCE] Brand context injected: {len(parts)} fields")
        else:
            logger.info("[ENHANCE] No brand context — generating generic directions")

        # ── Platform context ─────────────────────────────────────────────────
        platform_section = ""
        if platform:
            platform_hints = {
                "instagram": "Instagram — aspirational, visually stunning, lifestyle-driven. Square or portrait format.",
                "facebook":  "Facebook — relatable, community-focused, slightly longer narrative visuals.",
                "linkedin":  "LinkedIn — professional, achievement-oriented, clean and credible.",
                "twitter":   "Twitter/X — bold, punchy, high-contrast visuals that read at a glance.",
            }
            hint = platform_hints.get(platform.lower(), platform)
            platform_section = f"\n\nTARGET PLATFORM: {hint}"

        # ── Posting goal context ─────────────────────────────────────────────
        goal_section = ""
        if posting_goal:
            guidance = _GOAL_GUIDANCE.get(posting_goal.lower(), f"Goal: {posting_goal}")
            goal_section = f"\n\nPOSTING GOAL: {guidance}"

        prompt = f"""You are a Senior Creative Director at a world-class advertising agency — the caliber of Wieden+Kennedy, Ogilvy, BBDO, or Droga5. You specialize in writing visual creative briefs for AI-powered marketing post generation.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW YOUR OUTPUT IS USED — READ THIS FIRST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The scene_description you write will be injected as the "CREATIVE BRIEF" inside a
Gemini image generation prompt. That prompt already contains:
  ✓ Company name, brand voice, and brand colors
  ✓ Product/service name, description, features, and benefits
  ✓ Posting goal and emotional tone
  ✓ Target platform and format (1080×1350 portrait)
  ✓ Logo placement instructions
  ✓ Typography design rules

So your brief must NOT repeat any of the above. It must ONLY supply what the system
cannot derive on its own: the specific VISUAL CONCEPT — the scene, composition,
lighting treatment, visual style, and the emotional story of the image.

Your output is what makes the difference between a generic AI post and a campaign-quality image.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S BRIEF:
"{user_prompt}"{brand_section}{platform_section}{goal_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — IDENTIFY THE INDUSTRY
Before writing, determine what industry this is. Then apply its proven visual language:
  • F&B / Restaurants → texture-first, steam, condensation, overhead flat-lays, moody ambiance, cross-sections
  • Fashion / Apparel → editorial framing, fabric texture close-ups, hard shadow contrast, runway or street energy
  • Technology / SaaS → human hands on devices, glowing interfaces in dark environments, sharp geometry, clean negative space
  • Healthcare / Wellness → soft wrap light, clinical whites, human connection, nature metaphors, calm and trust
  • Finance / Professional Services → confidence-radiating portraits, architectural precision, premium materials, city backdrops
  • Real Estate / Interior → natural window flood, lifestyle staging, wide angles, aspirational space and light
  • Beauty / Skincare → macro textures, water droplets on skin, diverse skin tones, soft studio wrap, product on surface
  • Fitness / Sports → motion freeze or blur, explosive body language, sweat and effort, dramatic light from below or behind
  • Education / E-learning → screen-lit faces, breakthrough expressions, collaborative spaces, diverse learners
  • Retail / E-commerce → desire-inducing isolation shots, lifestyle in-use, unboxing moments, seasonal texture and light
  • Automotive → low camera angle, motion context, material close-ups, dramatic environment (rain, city night, open road)
  • Food & Beverage (CPG) → hero product with appetite appeal, styled props, backlit liquids, surface texture contrast

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — WRITE 3 CREATIVE DIRECTIONS

Each scene_description is a 4-5 sentence creative brief written as a direct instruction
to the Gemini image generation model. Structure each as:

  S1 — THE VISUAL CONCEPT: What is the scene? What is the central subject, action, or
       moment? Be specific and concrete — name exact objects, settings, materials, and
       what is happening. Not "a product shot" but "a single matte black bottle resting
       on a rough-hewn slate surface, moisture beading on its shoulder from the cold."

  S2 — COMPOSITION & CAMERA: Camera height and angle. Where the subject sits in the
       frame. How much negative space, and on which side (for text overlay). Depth of
       field intention. Tight/wide. Rule of thirds or center lock.

  S3 — ENVIRONMENT & SUPPORTING ELEMENTS: What surfaces, props, and background
       elements build the world around the subject? Every noun must be specific.
       Not "a table" but "a weathered teak surface with grain lines running left to right."

  S4 — LIGHT & COLOR: Light source (window / studio / practicals / natural), direction
       (45-degree from upper left / backlit / overhead), quality (hard/soft/diffused),
       color temperature (warm tungsten / cool daylight / golden hour), dominant palette,
       and how shadows behave. This sentence determines the entire emotional register.

  S5 — VISUAL STYLE + EMOTIONAL PAYOFF: Name a visual style reference (a photographer,
       campaign, or publication aesthetic). Then state what the viewer feels and desires —
       the marketing payoff. This is the last thing the model reads; make it land.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
THE 3 TERRITORIES — must be genuinely different creative strategies, not variations:

  OPTION 1 — DESIRE ARCHITECTURE
  Elevate the product or service to an art object. Every compositional and lighting
  decision exists to make the viewer want to possess it, taste it, wear it, or use it.
  The product or its direct promise IS the entire world of the image.
  Tone: aspirational, precise, seductive. Think Apple, Rolex, Chanel, Aesop, Supreme.

  OPTION 2 — AUTHENTIC HUMAN TRUTH
  A specific, unguarded human moment — not a pose, not a model smiling at the camera.
  A behavioral truth the target audience recognizes as their own life. The product may be
  present or implied, but the human moment is the reason to stop scrolling.
  Tone: warm, real, intimate. Think Dove, Airbnb, Patagonia, Nike "Just Do It", Spotify.

  OPTION 3 — BRAND MYTHOLOGY
  The aspirational world this brand lives in — no product required. Just the environment,
  the texture, the energy, the culture. The viewer wants to belong here.
  Tone: cinematic, bold, world-building. Think Red Bull, Louis Vuitton, Tesla, Patagonia wilderness.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
QUALITY RULES — enforce on every option:
  ✗ No vague words: beautiful, amazing, stunning, nice, great, perfect, wonderful, sleek
  ✗ No mention of logos, fonts, colors, or text overlays (pipeline handles this)
  ✗ No generic nouns — every object must be specific and material
  ✗ No more than 5 sentences
  ✗ No overlap between options — different scene, different light, different emotional register
  ✓ Leave compositional space (one side of frame) for text/logo overlay
  ✓ Apply the industry visual language identified in Step 1
  ✓ Consider cultural relevance if the brand context suggests a specific market

EXAMPLE scene_description (artisan brand — for reference only, do NOT copy):
"A master glassblower in his early 50s, forearms darkened with carbon, holds a glowing amber gather on an iron pipe at the precise moment it begins to elongate — liquid fire obeying gravity and breath. Shot from waist height at a slight upward angle, the subject anchors the left two-thirds of the frame; the right third is open dark air with no competing elements, space held for a headline. The workshop floor is raw concrete dusted with ash, iron hooks suspended from timber joists above, a distant furnace portal casting a deep orange glow through iron bars behind him. The scene is lit almost entirely by the gather itself — fierce 2700K center cooling to deep amber at the edges, hard shadows raking across his knuckles and jaw. Photographed in the style of Eugene Smith's industrial documentary intimacy — the viewer understands immediately that some things are still made by human hands, and that is precisely the point."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RESPOND WITH VALID JSON ONLY:
{{
    "options": [
        {{
            "title": "3-6 word campaign concept name",
            "scene_description": "S1 visual concept. S2 composition and camera. S3 environment and props. S4 light and color. S5 visual style reference and emotional payoff."
        }},
        {{
            "title": "3-6 word campaign concept name",
            "scene_description": "Human truth version — 5 sentences across the 5 structure points."
        }},
        {{
            "title": "3-6 word campaign concept name",
            "scene_description": "Brand mythology version — 5 sentences across the 5 structure points."
        }}
    ]
}}

NO markdown, NO explanation, ONLY the JSON object."""

        logger.info(f"[ENHANCE] Prompt built — {len(prompt)} chars, sending to Gemini ({gemini_model})...")

        try:
            from google.genai import types

            gemini_start = time.time()
            response = await gemini_client.aio.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=1.0,
                ),
            )
            gemini_elapsed = time.time() - gemini_start
            logger.info(f"[ENHANCE] Gemini responded in {gemini_elapsed:.2f}s")

            # Bulletproof text extraction (same pattern as utils.py)
            response_text = None
            if hasattr(response, "text") and response.text:
                response_text = response.text.strip()
            elif hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and candidate.content:
                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, "text") and part.text:
                                response_text = part.text.strip()
                                break

            if not response_text:
                # Check for blocked prompt
                if hasattr(response, "prompt_feedback") and response.prompt_feedback:
                    logger.error(f"[ENHANCE] Prompt BLOCKED by safety filter: {response.prompt_feedback}")
                    raise HTTPException(status_code=422, detail="Prompt was blocked by safety filters — please rephrase your idea")
                logger.error("[ENHANCE] Gemini returned empty response (no text in any candidate)")
                raise HTTPException(status_code=502, detail="AI returned empty response — please try again")

            logger.info(f"[ENHANCE] Raw response length: {len(response_text)} chars")
            logger.debug(f"[ENHANCE] Raw response preview: {response_text[:300]}...")

            # Log token usage
            usage = getattr(response, "usage_metadata", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_token_count", "?")
                output_tokens = getattr(usage, "candidates_token_count", "?")
                logger.info(f"[ENHANCE] Tokens: prompt={prompt_tokens}, output={output_tokens}")

            # Clean markdown fences
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
                logger.debug("[ENHANCE] Stripped ```json markdown fences")
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
                logger.debug("[ENHANCE] Stripped ``` markdown fences")

            # Extract JSON object
            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    response_text = response_text[start_idx:end_idx]
                    logger.debug(f"[ENHANCE] Extracted JSON substring [{start_idx}:{end_idx}]")

            result = json.loads(response_text)
            options_raw = result.get("options", [])
            logger.info(f"[ENHANCE] JSON parsed successfully — {len(options_raw)} options received")

            if not options_raw or len(options_raw) < 1:
                logger.error(f"[ENHANCE] No options in parsed JSON. Keys: {list(result.keys())}")
                raise ValueError("No options returned")

            # Build validated options (take up to 3)
            options = []
            for idx, opt in enumerate(options_raw[:3]):
                title = opt.get("title", "Untitled Option")
                scene = opt.get("scene_description", "")
                logger.info(f"[ENHANCE]   Option {idx + 1}: \"{title}\" — {len(scene)} chars")
                options.append(PromptOption(
                    title=title,
                    scene_description=scene,
                ))

            total_elapsed = time.time() - start_time
            logger.info(f"[ENHANCE] SUCCESS — {len(options)} options generated in {total_elapsed:.2f}s for: '{user_prompt[:60]}'")
            logger.info("=" * 60)

            return PromptEnhancerResponse(
                original_prompt=user_prompt,
                options=options,
            )

        except json.JSONDecodeError as e:
            total_elapsed = time.time() - start_time
            logger.error(f"[ENHANCE] JSON parse failed after {total_elapsed:.2f}s: {e}")
            logger.error(f"[ENHANCE] Raw response ({len(response_text) if response_text else 0} chars): {response_text[:500] if response_text else 'None'}")
            raise HTTPException(status_code=502, detail="AI response could not be parsed — please try again")

        except HTTPException:
            raise

        except Exception as e:
            total_elapsed = time.time() - start_time
            logger.error(f"[ENHANCE] FAILED after {total_elapsed:.2f}s: {type(e).__name__}: {e}")
            raise HTTPException(status_code=500, detail=f"Prompt enhancement failed: {str(e)}")

    return router