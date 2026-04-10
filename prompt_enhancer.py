"""
Prompt Enhancer — takes a rough user idea + reference images, post objective,
platform, and variant count, then generates N detailed visual scene options.
User picks one and feeds it as image_prompt to /create-campaign-advanced or custom_prompt to /smart-post.
"""
import base64
import json
import logging
import time
from typing import List, Optional

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile

from models import PromptEnhancerResponse, PromptOption
from utils import download_reference_image, process_uploaded_reference_image

logger = logging.getLogger("quicksocial.prompt_enhancer")

# Max reference images allowed per request
_MAX_REFERENCE_IMAGES = 5

# Post objective → creative direction hints for the prompt
_OBJECTIVE_DIRECTIVES = {
    "Promotional":      "Focus on product/service hero shots, offers, discounts, and compelling CTAs. Showcase value and urgency.",
    "Engagement":       "Prioritise relatable, shareable, emotionally resonant visuals that invite comments and reactions. Think conversation starters.",
    "Announcement":     "Create bold, attention-grabbing visuals for news, launches, or updates. Emphasise novelty and importance.",
    "Brand Awareness":  "Design distinctive, memorable visuals that reinforce brand identity, colors, and values. Think billboard-level impact.",
    "Festival/Event":   "Incorporate festive/event-specific motifs, cultural symbols, warm colors, and celebratory energy.",
}

# Platform → visual style hints
_PLATFORM_HINTS = {
    "instagram":  "Instagram favors bold visuals, vibrant colors, clean compositions, and 1:1 or 4:5 aspect ratios. Stories use 9:16.",
    "facebook":   "Facebook images work best at 16:9 or 1:1. Slightly more informational — text overlays and context perform well.",
    "linkedin":   "LinkedIn prefers polished, professional imagery. Corporate tones, clean typography, muted palettes. 16:9 landscape.",
    "twitter":    "Twitter/X images should be punchy and instantly readable at small sizes. 16:9 landscape. Bold, high-contrast.",
    "whatsapp":   "WhatsApp status images are viewed full-screen on mobile — 9:16 vertical, vivid, minimal text, personal feel.",
    "youtube":    "YouTube thumbnails need extreme contrast, expressive faces, large text, 16:9 landscape.",
}


def create_prompt_enhancer_router(gemini_client, gemini_model):
    router = APIRouter(tags=["Prompt Enhancer"])

    @router.post("/enhance-prompt", response_model=PromptEnhancerResponse)
    async def enhance_prompt(
        request: Request,
        user_prompt: str = Form(..., description="Your rough idea for the image — can be as vague or detailed as you like"),
        company_name: Optional[str] = Form(None, description="Company name for brand-relevant scenes"),
        company_description: Optional[str] = Form(None, description="Brief company description for context"),
        brand_voice: Optional[str] = Form(None, description="Brand voice/tone (e.g., 'luxury', 'playful', 'corporate')"),
        # --- Post context ---
        post_objective: Optional[str] = Form(None, description="Post objective: Promotional, Engagement, Announcement, Brand Awareness, Festival/Event"),
        platforms: Optional[str] = Form(None, description="Comma-separated platforms: instagram,facebook,linkedin,twitter,whatsapp,youtube"),
        # --- Reference image URLs ---
        reference_image_url_1: Optional[str] = Form(None, description="Reference image 1 (URL)"),
        reference_image_url_2: Optional[str] = Form(None, description="Reference image 2 (URL)"),
        reference_image_url_3: Optional[str] = Form(None, description="Reference image 3 (URL)"),
        reference_image_url_4: Optional[str] = Form(None, description="Reference image 4 (URL)"),
        reference_image_url_5: Optional[str] = Form(None, description="Reference image 5 (URL)"),
    ):
        """
        Analyze a rough user prompt and generate 3 distinct visual scene options.

        Each option is a detailed, production-ready image directive that can be
        directly passed as `image_prompt` to /create-campaign-advanced or
        `custom_prompt` to /smart-post.

        Reference images can be provided via file upload (reference_image_1..5
        as multipart files) or URL (reference_image_url_1..5). For each slot,
        file upload takes priority over URL. Up to 5 total.
        """
        start_time = time.time()

        variants = 3

        # Parse platforms list
        platform_list = []
        if platforms and platforms.strip():
            platform_list = [p.strip().lower() for p in platforms.split(",") if p.strip()]

        # ── Extract file uploads from raw form (avoids FastAPI "null" string crash) ──
        file_uploads = {}  # slot index → UploadFile
        try:
            form = await request.form()
            for i in range(1, 6):
                key = f"reference_image_{i}"
                if key in form:
                    val = form[key]
                    if isinstance(val, UploadFile) and val.filename and val.size and val.size > 0:
                        file_uploads[i] = val
        except Exception:
            pass

        url_slots = {
            1: reference_image_url_1, 2: reference_image_url_2, 3: reference_image_url_3,
            4: reference_image_url_4, 5: reference_image_url_5,
        }

        # Each entry: (base64_data, mime_type, label)
        resolved_refs: List[tuple] = []

        for idx in range(1, 6):
            if len(resolved_refs) >= _MAX_REFERENCE_IMAGES:
                break

            # Priority 1: File upload
            if idx in file_uploads:
                try:
                    file_slot = file_uploads[idx]
                    file_bytes = await file_slot.read()
                    if file_bytes:
                        result = process_uploaded_reference_image(file_bytes, file_slot.filename)
                        if result and result.get("success"):
                            resolved_refs.append((result["base64_data"], result["mime_type"], f"upload:{file_slot.filename}"))
                            continue
                except Exception as e:
                    logger.warning(f"[ENHANCE] Ref image {idx} upload failed: {e}")

            # Priority 2: URL download
            url_slot = url_slots.get(idx)
            if url_slot and url_slot.strip() and url_slot.strip().lower() not in ("null", "string", "undefined", ""):
                try:
                    result = download_reference_image(url_slot.strip())
                    if result and result.get("success"):
                        resolved_refs.append((result["base64_data"], result["mime_type"], f"url:{url_slot.strip()}"))
                except Exception as e:
                    logger.warning(f"[ENHANCE] Ref image {idx} URL download failed: {e}")

        logger.info("=" * 60)
        logger.info("[ENHANCE] New request received")
        logger.info(f"[ENHANCE] User prompt: '{user_prompt}'")
        logger.info(f"[ENHANCE] Company: {company_name or '(none)'}")
        logger.info(f"[ENHANCE] Post objective: {post_objective or '(none)'}")
        logger.info(f"[ENHANCE] Platforms: {platform_list or '(none)'}")
        logger.info(f"[ENHANCE] Reference images: {len(resolved_refs)}")
        for ref_b64, ref_mime, ref_label in resolved_refs:
            logger.info(f"[ENHANCE]   -> {ref_label} ({ref_mime})")

        # ── Build Gemini contents (multimodal: images + text) ──────────
        contents = []

        # Add reference images first (so Gemini sees them before the prompt)
        for ref_b64, ref_mime, _ in resolved_refs:
            contents.append({
                "inline_data": {
                    "mime_type": ref_mime,
                    "data": ref_b64,
                }
            })

        ref_count = len(resolved_refs)
        if ref_count > 0:
            contents.append(
                f"REFERENCE IMAGES: I've provided {ref_count} reference image(s) above. "
                "Use them as visual inspiration — match their color palette, mood, composition style, "
                "or subject matter where relevant. Do NOT describe these images literally; instead, "
                "let them influence the creative direction of your scene options."
            )

        # ── Build brand context ──────────────────────────────────────
        brand_section = ""
        if company_name or company_description or brand_voice:
            parts = []
            if company_name:
                parts.append(f"Company: {company_name}")
            if company_description:
                parts.append(f"Industry/Description: {company_description[:200]}")
            if brand_voice:
                parts.append(f"Brand Voice: {brand_voice}")
            brand_section = f"""
BRAND CONTEXT (tailor scenes to this brand):
{chr(10).join(parts)}
"""

        # ── Build objective section ──────────────────────────────────
        objective_section = ""
        if post_objective and post_objective.strip():
            directive = _OBJECTIVE_DIRECTIVES.get(post_objective.strip(), "")
            objective_section = f"""
POST OBJECTIVE: {post_objective}
Creative direction: {directive}
Every option MUST serve this objective — the visuals should clearly support "{post_objective}" goals.
"""

        # ── Build platform section ───────────────────────────────────
        platform_section = ""
        if platform_list:
            hints = []
            for p in platform_list:
                hint = _PLATFORM_HINTS.get(p)
                if hint:
                    hints.append(f"  - {p.title()}: {hint}")
            if hints:
                platform_section = f"""
TARGET PLATFORMS:
{chr(10).join(hints)}
Consider these platform-specific visual conventions when designing each scene. If multiple platforms are listed, optimize for the FIRST one but ensure the scenes work across all.
"""

        # ── Build variety instructions based on variant count ────────
        variety_block = """Generate exactly 3 visual options. ALL 3 must be faithful to the user's original idea — they are ENHANCEMENTS of the same concept, NOT different concepts. Vary the camera angle, lighting, composition, and setting, but the core subject/message must remain what the user described.

VARIETY GUIDELINES:
- Option 1: The most direct, polished version of exactly what the user described — elevated with professional-grade detail
- Option 2: Same core idea, different visual angle — e.g., different camera perspective, framing, or environment while keeping the same subject and message
- Option 3: Same core idea, different mood/atmosphere — e.g., different lighting, time of day, or emotional tone while keeping the same subject and message"""

        # ── Assemble final prompt ────────────────────────────────────
        prompt = f"""You are an elite creative director at a top advertising agency. A client has described their vision for a marketing image. Your job is to ENHANCE their idea into 3 production-ready visual scene directions.

IMPORTANT: The user's idea is the foundation — you are ENHANCING it, not replacing it. Every option must clearly reflect what the user asked for. If they said "coffee shop scene", all 3 options must be coffee shop scenes. If they said "product on a table", all 3 must show the product on a table. You are adding professional detail, not changing the concept.

USER'S IDEA (this is what ALL options must be based on):
"{user_prompt}"
{brand_section}{objective_section}{platform_section}{"REFERENCE IMAGES were provided above — use them as visual inspiration while staying true to the user's idea." if ref_count > 0 else ""}

────────────────────────────────────────
INTENT PRESERVATION FRAMEWORK (MANDATORY)
────────────────────────────────────────

Step 1 — Extract Core Intent from the user's prompt:
- SUBJECT: What is being promoted? (product, service, platform, event, offer, etc.)
- ACTION: What does it do or what is happening? (e.g., generates posts, sells products, enables booking)
- CONTEXT: Where/how is it happening? (scene, environment, setting)

Step 2 — Visual Grounding (NON-NEGOTIABLE):
Every generated scene MUST visually represent BOTH:
1. The SUBJECT (what is being promoted)
2. The ACTION (what it does)

These must be visible in the scene — NOT implied.

────────────────────────────────────────
VISUALIZATION RULES
────────────────────────────────────────

If SUBJECT is digital (app, platform, AI, software):
→ Show it ON SCREEN (laptop, phone, UI, dashboards)

If SUBJECT is physical (product, clothing, food, etc.):
→ Show the product clearly as the focal point

If SUBJECT is a service:
→ Show the service being performed or experienced

If SUBJECT is abstract (AI, growth, automation):
→ Represent it via UI, transformation, data flow, or visible output

────────────────────────────────────────
ACTION VISIBILITY RULE
────────────────────────────────────────

The core ACTION must be visually understandable.

BAD:
"A team working in an office"

GOOD:
"A team working on laptops where the platform is actively generating outputs visible on their screens"

────────────────────────────────────────
SCENE BALANCE RULE
────────────────────────────────────────

- Preserve the user's described scene
- Integrate SUBJECT + ACTION into that scene
- Scene supports the idea, not replaces it

────────────────────────────────────────
FAIL CONDITION (STRICT)
────────────────────────────────────────

If someone sees the image and cannot answer:
"What is this post promoting?"

→ The output is INVALID

────────────────────────────────────────
VARIETY GUIDELINES
────────────────────────────────────────

Generate exactly 3 visual options. ALL 3 must be faithful to the user's original idea — they are ENHANCEMENTS of the same concept.

- Option 1: Direct, polished version of the user's idea
- Option 2: Same idea, different composition/camera angle
- Option 3: Same idea, different mood/lighting/atmosphere

────────────────────────────────────────
CRITICAL COLOR RULE
────────────────────────────────────────

Do NOT specify any exact colors or color names.
Describe only lighting and tonal qualities (e.g., "warm lighting", "high contrast", "soft shadows")

────────────────────────────────────────
SCENE DESCRIPTION REQUIREMENTS
────────────────────────────────────────

Each scene_description MUST include:

- WHAT is being promoted (clearly visible)
- HOW it works or what it does (visually represented)
- WHERE it is happening (scene)
- WHO is interacting (if applicable)
- WHAT is visible on screen/product (MANDATORY for digital products)

The product/service MUST be visible — NOT implied.

────────────────────────────────────────
OUTPUT FORMAT
────────────────────────────────────────

For each option provide:
- title: A short, evocative label (3-6 words)
- scene_description: A detailed, vivid description (2-4 sentences)
- mood: Emotional atmosphere (1 sentence)
- style: Photography/visual style (1 sentence)

RESPOND WITH VALID JSON ONLY:
{{
    "options": [
        {{
            "title": "Short Evocative Title",
            "scene_description": "Detailed visual description...",
            "mood": "Emotional atmosphere...",
            "style": "Photography approach..."
        }}
    ]
}}

NO markdown, NO explanation, ONLY the JSON object."""

        contents.append(prompt)

        logger.info(f"[ENHANCE] Prompt built — {len(prompt)} chars, {ref_count} ref images, sending to Gemini ({gemini_model})...")

        try:
            from google.genai import types

            gemini_start = time.time()
            response = await gemini_client.aio.models.generate_content(
                model=gemini_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.9,
                ),
            )
            gemini_elapsed = time.time() - gemini_start
            logger.info(f"[ENHANCE] Gemini responded in {gemini_elapsed:.2f}s")

            # Bulletproof text extraction
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
                if hasattr(response, "prompt_feedback") and response.prompt_feedback:
                    logger.error(f"[ENHANCE] Prompt BLOCKED by safety filter: {response.prompt_feedback}")
                    raise HTTPException(status_code=422, detail="Prompt was blocked by safety filters — please rephrase your idea")
                logger.error("[ENHANCE] Gemini returned empty response (no text in any candidate)")
                raise HTTPException(status_code=502, detail="AI returned empty response — please try again")

            logger.info(f"[ENHANCE] Raw response length: {len(response_text)} chars")

            # Log token usage
            usage = getattr(response, "usage_metadata", None)
            if usage:
                prompt_tokens = getattr(usage, "prompt_token_count", "?")
                output_tokens = getattr(usage, "candidates_token_count", "?")
                logger.info(f"[ENHANCE] Tokens: prompt={prompt_tokens}, output={output_tokens}")

            # Clean markdown fences
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            # Extract JSON object
            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    response_text = response_text[start_idx:end_idx]

            result = json.loads(response_text)
            options_raw = result.get("options", [])
            logger.info(f"[ENHANCE] JSON parsed — {len(options_raw)} options received (requested {variants})")

            if not options_raw or len(options_raw) < 1:
                logger.error(f"[ENHANCE] No options in parsed JSON. Keys: {list(result.keys())}")
                raise ValueError("No options returned")

            # Build validated options (take up to requested count)
            options = []
            for idx, opt in enumerate(options_raw[:variants]):
                title = opt.get("title", "Untitled Option")
                scene = opt.get("scene_description", "")
                mood = opt.get("mood", "")
                style = opt.get("style", "")
                logger.info(f"[ENHANCE]   Option {idx + 1}: \"{title}\" — {len(scene)} chars")
                options.append(PromptOption(
                    title=title,
                    scene_description=scene,
                    mood=mood,
                    style=style,
                ))

            total_elapsed = time.time() - start_time
            logger.info(f"[ENHANCE] SUCCESS — {len(options)} options in {total_elapsed:.2f}s")
            logger.info("=" * 60)

            return PromptEnhancerResponse(
                original_prompt=user_prompt,
                post_objective=post_objective,
                platforms=platform_list or None,
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