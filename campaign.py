from fastapi import APIRouter, HTTPException, Form, UploadFile, File, WebSocket, WebSocketDisconnect
from google.genai import types
from typing import Optional, Dict, List, Any
from datetime import datetime
from pathlib import Path
import json
import uuid
import re
import base64
import logging
import traceback
import asyncio
import time
import os

from models import (
    CampaignGoal, ContentType, ContentStrategy,
    CampaignProduct, CampaignService, Feature, RequiredSkill,
    GeneratedPost, CampaignResponse,
    CAMPAIGN_PLATFORM_SPECS, CAMPAIGN_TEXT_MODEL
)
from utils import (
    extract_gemini_text, log_gemini_usage,
    save_campaign_image,
    download_reference_image, process_uploaded_reference_image,
    build_product_image_context, generate_caption_and_hashtags,
    hybrid_company_understanding, generate_brand_awareness_items,
    resize_image_for_platform, build_brand_payload,
)
from prompt_guards import NEGATIVE_PROMPT, TYPOGRAPHY_PRECISION, REALISM_STANDARD, SPELLING_PRIORITY_PREAMBLE

logger = logging.getLogger(__name__)


def create_campaign_router(gemini_client, gemini_model, image_model, storage_dir):
    router = APIRouter(tags=["Campaign"])
    campaign_job_store: Dict[str, dict] = {}
    _HEARTBEAT_INTERVAL_SECONDS = 8

    # File-based persistence so reconnecting clients can retrieve completed results
    _campaign_jobs_dir = Path(storage_dir) / "campaign_jobs"
    _campaign_jobs_dir.mkdir(parents=True, exist_ok=True)

    def _persist_job(job_id: str, data: dict) -> None:
        try:
            (_campaign_jobs_dir / f"_job_{job_id}.json").write_text(
                json.dumps(data, default=str), encoding="utf-8"
            )
        except Exception:
            pass

    def _append_event(job_id: str, event: dict) -> None:
        """Append a progress event to the job's events file (enables cross-instance streaming)."""
        try:
            events_file = _campaign_jobs_dir / f"_job_{job_id}.events.jsonl"
            with open(events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except Exception:
            pass

    def _read_persisted_job(job_id: str) -> Optional[dict]:
        try:
            f = _campaign_jobs_dir / f"_job_{job_id}.json"
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    async def _campaign_heartbeat(job_id: str, queue: asyncio.Queue, stop_event: asyncio.Event) -> None:
        """Emit periodic keepalive events while long-running model calls are in flight."""
        try:
            while not stop_event.is_set():
                await asyncio.sleep(_HEARTBEAT_INTERVAL_SECONDS)
                if stop_event.is_set():
                    break
                heartbeat_event = {
                    "step": "heartbeat",
                    "message": "Gemini is still processing your campaign. Please keep this window open.",
                }
                await queue.put(heartbeat_event)
                _append_event(job_id, heartbeat_event)
        except asyncio.CancelledError:
            raise

    async def _stop_background_task(task: Optional[asyncio.Task], stop_event: Optional[asyncio.Event] = None) -> None:
        """Signal and await helper tasks cleanly."""
        if stop_event is not None:
            stop_event.set()
        if not task:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _ordinal(n: int) -> str:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
        return f"{n}{suffix}"

    def _get_goal_focus(goal: str) -> str:
        """Return design focus based on campaign goal"""
        goal_mapping = {
            "Brand awareness": "Introduce brand personality, showcase company values, build emotional connection, make it memorable. Always use creative approach",
            "Lead generation": "Highlight unique value proposition, create curiosity, emphasize benefits, encourage contact/signup. Be diverse with the sentence formation",
            "Sales & conversion": "Emphasize transformation and ROI, create urgency with limited offers, show social proof, strong value messaging. Always use different approach",
            "Engagement": "Tell compelling stories, ask engaging questions, encourage shares and comments, build community feeling. Smart sentences should be picked to engage the customers",
            "Customer retention": "Show appreciation for loyalty, highlight exclusive benefits, create sense of belonging, recognize customer achievements. Always pursue the customer is unique ways"
        }
        return goal_mapping.get(goal, "Highlight product/service value and quality")
    
    def _get_emotional_hook(goal: str) -> str:
        """Return emotional hook based on campaign goal"""
        goal_mapping = {
            "Brand awareness": "CURIOSITY - Make them want to know more about this brand however do not always starts with questioining pattern such as did you know?",
            "Lead generation": "INTEREST - Create desire to learn more and take action. Use unique tonality",
            "Sales & conversion": "DESIRE + URGENCY - Make them want to buy NOW. Use customer centric approach",
            "Engagement": "CONNECTION - Make them feel part of a community",
            "Customer retention": "LOYALTY + GRATITUDE - Make them feel valued and special"
        }
        return goal_mapping.get(goal, "BUILD TRUST - Show value and quality")

    def _get_campaign_goal_caption_direction(goal: str) -> str:
        """Caption tone, structure, and CTA strategy per campaign goal — turns the goal into an actionable writing directive"""
        mapping = {
            "Brand awareness": (
                "STORY-FIRST, CURIOSITY-LED. Open with something memorable about the brand — a belief, a vision, or an origin moment. "
                "The goal is to make the reader feel something and want to know more. Do NOT lead with a product feature. Lead with identity. "
                "CTA style: 'Discover who we are', 'Learn our story', 'Follow to stay inspired', 'Join the journey'."
            ),
            "Lead generation": (
                "VALUE-FIRST, INTEREST-GENERATING. Open with the single most compelling benefit or outcome this offering delivers. "
                "Speak directly to the reader's problem or aspiration. Build enough curiosity and credibility that they feel compelled to reach out. "
                "CTA style: 'Get started today', 'Book a free consultation', 'Contact us to learn more', 'Claim your free trial'."
            ),
            "Sales & conversion": (
                "DESIRE + URGENCY. Open with the transformation or result — what the buyer gains. Make the value undeniable in the first line. "
                "Include price, discount, or offer details directly in the caption (the image handles visuals, the caption closes the sale). Create urgency without desperation. "
                "CTA style: 'Shop now', 'Order today', 'Limited offer — grab yours', 'Only [X] left — act fast'."
            ),
            "Engagement": (
                "CONVERSATION-STARTER, COMMUNITY-FIRST. Open with a question, a bold opinion, or a relatable observation that makes the reader stop and react. "
                "The caption should feel like the start of a conversation, not a broadcast. Invite responses, shares, and tags. "
                "CTA style: 'Tell us in the comments', 'Tag someone who needs this', 'Share your experience', 'Drop a ❤️ if you agree'."
            ),
            "Customer retention": (
                "GRATITUDE-LED, EXCLUSIVE FEEL. Open by acknowledging the reader as a valued part of the brand's community. "
                "Make long-term customers feel seen, appreciated, and rewarded — not like they're being sold to. Highlight exclusivity or loyalty benefits. "
                "CTA style: 'For our valued members', 'Exclusively for you', 'A thank-you from us', 'Because you deserve more'."
            ),
        }
        return mapping.get(goal, "Caption aligned with the brand voice — communicate value clearly and end with a compelling call-to-action.")

    def _get_visual_approach(item_type: str, goal: str, item_name: str = "") -> str:
        """Auto-select the single best visual approach based on item type and campaign goal"""
        _n = item_name or "this"
        _t = item_type.lower()
        approach_map = {
            ("product", "Brand awareness"):     ("PRODUCT/SERVICE HERO",     f"The product '{_n}' IS the image — capture its form, texture, and character in exquisite photographic detail. Let the object speak."),
            ("product", "Sales & conversion"):  ("PRODUCT/SERVICE HERO",     f"'{_n}' centre-stage in its most desirable form — context that amplifies desire and urgency. Nothing competes with the product."),
            ("product", "Lead generation"):     ("MATERIAL & CRAFT DETAIL",  f"Macro intimacy — reveal the surface quality and detail of '{_n}' that signals premium value and earns trust before a word is read."),
            ("product", "Engagement"):          ("EDITORIAL LIFESTYLE",      f"Show '{_n}' in a real, authentic moment — people using it, loving it, in a scene the audience recognizes and wants to be part of."),
            ("product", "Customer retention"):  ("EDITORIAL LIFESTYLE",      f"Loyal users of '{_n}' in their element — show belonging, pride of ownership, the lived relationship with the product."),
            ("service", "Brand awareness"):     ("CONCEPTUAL/ABSTRACT",      f"Visualize the OUTCOME '{_n}' creates — the feeling and transformation, not the process. Make the intangible tangible."),
            ("service", "Sales & conversion"):  ("EDITORIAL LIFESTYLE",      f"Real person experiencing the benefit of '{_n}' — genuine emotion, aspirational energy. Show the after, not the before."),
            ("service", "Lead generation"):     ("ARCHITECTURAL/ENVIRON.",   f"The environment where '{_n}' operates — credible, aspirational, professional. Build trust through space and atmosphere."),
            ("service", "Engagement"):          ("EDITORIAL LIFESTYLE",      f"Community energy — genuine human moments, the culture and people '{_n}' brings together."),
            ("service", "Customer retention"):  ("EDITORIAL LIFESTYLE",      f"Long-term clients of '{_n}' — loyalty, gratitude, the relationship that grows over time."),
            ("brand",   "Brand awareness"):     ("BRAND POSITIONING",        f"'{_n}' brand essence through positioning — show what this brand STANDS FOR, its core values and purpose. The image should communicate the brand's unique positioning in the market, not through decoration but through authentic brand expression. Show the brand's world, audience connection, and why this brand matters."),
            ("brand",   "Sales & conversion"):  ("BRAND POSITIONING",        f"'{_n}' brand promise made visual — communicate the trust, quality, and value this brand delivers through its positioning. Use brand colors, typography, and authentic visual language to show what makes this brand the choice. Focus on brand positioning and differentiation, not generic appeal."),
            ("brand",   "Lead generation"):     ("BRAND POSITIONING",        f"The '{_n}' brand universe — visualize the brand's positioning, values, and audience. Use brand's core visual DNA to show who this brand is for and what it stands for. Make the brand's market position and authentic identity visually clear using brand colors, voice, and authentic design language."),
            ("brand",   "Engagement"):          ("BRAND POSITIONING",        f"'{_n}' brand community and values — show the brand's authentic positioning through the people, culture, and values it represents. Use brand motifs and visual language to communicate what the brand stands for and who it serves. Make it feel like brand truth, not artistic interpretation."),
            ("brand",   "Customer retention"):  ("EDITORIAL LIFESTYLE",      f"Long-time lovers of '{_n}' — show the relationship, belonging, and earned loyalty. Gratitude and exclusivity."),
        }
        key = (_t, goal)
        if key in approach_map:
            name, desc = approach_map[key]
            return f"SELECTED APPROACH → {name}\n{desc}"
        # Fallback by type
        if _t == "product":
            return f"SELECTED APPROACH → PRODUCT/SERVICE HERO\n'{_n}' is the star — capture it at its most desirable and aspirational."
        elif _t == "service":
            return f"SELECTED APPROACH → EDITORIAL LIFESTYLE\nShow real people experiencing the transformation '{_n}' delivers."
        elif _t == "brand_theme":
            return f"SELECTED APPROACH → BRAND POSITIONING\n'{_n}' brand essence and positioning — communicate what the brand stands for, its core values, unique market position, and authentic visual identity. Show why this brand matters through authentic brand expression, using brand colors, voice, and visual language."
        return f"SELECTED APPROACH → BRAND POSITIONING\n'{_n}' brand positioning and values expressed authentically — show the brand's unique market position, core purpose, and visual identity. Communicate what makes this brand stand for through on-brand, positioned imagery."
    def _get_font_style(brand_voice: str) -> str:
        """Infer specific font family and weight style from brand voice"""
        if not brand_voice:
            return "Humanist sans-serif — clean, versatile, professional. Strong weight contrast between headline and subline."
        v = brand_voice.lower()
        if any(w in v for w in ["luxury", "heritage", "artisan", "premium", "classic", "elegant", "refined", "sophisticated", "craft", "couture", "bespoke", "haute", "cultural", "deep"]):
            return "HIGH-CONTRAST EDITORIAL SERIF (Didot / Bodoni style) — this is a luxury/heritage brand. Fine hairline strokes and high contrast signal craftsmanship and exclusivity. Bold weight headline, thin weight subline."
        elif any(w in v for w in ["tech", "innovation", "digital", "modern", "minimal", "clean", "precise", "futuristic", "smart", "data", "scientific", "engineering"]):
            return "GEOMETRIC SANS-SERIF (Futura / Montserrat style) — modern/tech brand. Tight tracking, rational letterforms, clean uppercase headline. Signals precision and forward momentum."
        elif any(w in v for w in ["creative", "fashion", "lifestyle", "playful", "warm", "casual", "vibrant", "expressive", "energetic", "youthful", "bold", "dynamic", "edgy"]):
            return "EXPRESSIVE DISPLAY (Bebas Neue / Abril Fatface style) — this brand has personality. Use the headline as a graphic element. Oversized, confident, with visual attitude."
        elif any(w in v for w in ["corporate", "professional", "trust", "reliable", "authority", "expert", "institutional", "credible", "law", "finance", "banking"]):
            return "HUMANIST SANS-SERIF (Gill Sans / Source Sans style) — approachable yet professional. Clean and legible at all sizes. Trustworthy gravitas without being cold."
        elif any(w in v for w in ["natural", "organic", "sustainable", "earth", "eco", "wellness", "health", "mindful", "botanical", "holistic"]):
            return "ORGANIC SERIF or HAND-CRAFTED style (Lora / Merriweather) — warm, grounded, connected to nature. Type that feels considered and human."
        return f"Typeface that embodies '{brand_voice}' — the font is part of the brand expression. Let the voice drive weight, spacing, and personality."

    def _get_content_type_image_direction(content_type: str) -> str:
        """Visual/compositional directives per content type — shapes the image aesthetic and typography pattern"""
        mapping = {
            "Educational": (
                "INFORMATION-FORWARD visual design. Clean, structured layout with clear hierarchy — premium infographic meets brand photography. "
                "Visualize a concept, process, or insight. Data or steps can be implied by the composition. "
                "TYPOGRAPHY HINT: Headline states a fact, insight, or 'Did you know?' style hook. Subline delivers the answer or key benefit clearly."
            ),
            "Promotional": (
                "OFFER-FORWARD visual design. Bold contrast, high desire, urgency energy. Product or service front-and-centre at its most aspirational. "
                "Scene amplifies value — what the buyer gains. Strong visual hierarchy drives the eye to the offer. "
                "TYPOGRAPHY HINT: Headline is the offer or bold value statement (e.g. 'EXCLUSIVE DEAL', 'SAVE NOW'). Subline reinforces the key benefit or urgency."
            ),
            "Entertainment": (
                "HIGH-ENERGY, expressive visual design. Dynamic composition with personality and attitude. Bold color, movement-suggestion, cultural relevance. "
                "The image should feel fun, alive, and shareable — not corporate. "
                "TYPOGRAPHY HINT: Headline is a punchy hook, attitude line, or cultural reference. Subline is a follow-through that earns a smile or share."
            ),
            "Inspirational": (
                "ASPIRATIONAL visual design. Epic environmental scale OR powerful emotional intimacy — choose one. "
                "The image should provoke a feeling: ambition, belonging, possibility, pride. Quiet grandeur or raw authenticity. "
                "TYPOGRAPHY HINT: Headline is a mantra, belief statement, or aspirational imperative (e.g. 'DARE TO BUILD', 'YOUR FUTURE STARTS HERE'). Subline is a softer emotional follow-through."
            ),
            "Announcement": (
                "REVEAL aesthetic — clean, authoritative, launch-energy. Something NEW is entering the world. Strong structural composition. "
                "The image should feel like an unveiling: confident, clear, memorable. No clutter — the announcement IS the design. "
                "TYPOGRAPHY HINT: Headline signals the reveal (e.g. 'INTRODUCING', 'IT'S HERE', 'NOW LIVE'). Subline states what it is and why it matters."
            ),
        }
        return mapping.get(content_type, "Visual design aligned with the campaign goal and brand identity.")

    def _get_content_type_caption_direction(content_type: str) -> str:
        """Caption tone, structure, and CTA guidance per content type"""
        mapping = {
            "Educational": (
                "EDUCATE, then earn the click. Open with a compelling fact, surprising stat, or thought-provoking question. "
                "Break down the value or insight in clear, jargon-free language. The reader should feel smarter after reading. "
                "CTA style: 'Learn more', 'Read the full story', 'Discover how', 'See how it works'."
            ),
            "Promotional": (
                "LEAD with the offer or transformation. Make the value undeniable in the first line. Create urgency — limited time, limited stock, or exclusive access. "
                "Include any price, discount, or offer details directly in the caption (not on the image). "
                "CTA style: 'Shop now', 'Claim your offer', 'Get yours today', 'Order before [date]'."
            ),
            "Entertainment": (
                "BE the entertainment. Open with a hook that earns attention in 2 seconds — humor, relatability, or cultural relevance. "
                "Conversational tone. Personality over polish. Invite participation and sharing. "
                "CTA style: 'Tag a friend who needs this', 'Share if you agree', 'Tell us in the comments', 'Save this for later'."
            ),
            "Inspirational": (
                "MOVE the reader emotionally before asking anything of them. Open with a belief statement, aspirational observation, or brand truth. "
                "Connect the brand's story to the reader's aspiration. Soft sell — the brand earns trust through emotion. "
                "CTA style: 'Start your journey', 'Join us', 'Believe in more', 'This is our story — what's yours?'"
            ),
            "Announcement": (
                "BUILD excitement from line one. Open with the reveal energy — 'It's here.', 'We've been waiting for this.', 'Introducing [X].' "
                "State clearly WHAT it is, WHY it matters, and WHEN/WHERE to access it. First-mover urgency. "
                "CTA style: 'Be the first to try it', 'Register now', 'Available from [date]', 'Click the link to discover more'."
            ),
        }
        return mapping.get(content_type, "Caption aligned with the brand voice, campaign goal, and platform tone.")


    # ═══════════════════════════════════════════════════════════════════════════
    # CLEANUP HELPER
    # ═══════════════════════════════════════════════════════════════════════════
    async def _cleanup_job(job_id: str, delay: int = 300):
        await asyncio.sleep(delay)
        campaign_job_store.pop(job_id, None)
        # Also remove the cross-instance events file
        try:
            (_campaign_jobs_dir / f"_job_{job_id}.events.jsonl").unlink(missing_ok=True)
        except Exception:
            pass
        logger.info(f"[WS] Cleaned up campaign job {job_id}")

    # ═══════════════════════════════════════════════════════════════════════════
    # BACKGROUND WORKER — full campaign generation with WS progress push
    # ═══════════════════════════════════════════════════════════════════════════
    async def _run_campaign_job(
        job_id: str,
        queue: asyncio.Queue,
        campaign_name: str,
        campaign_goal: CampaignGoal,
        num_posts: int,
        company_name: str,
        company_description: Optional[str],
        website: Optional[str],
        tagline: Optional[str],
        brand_voice: Optional[str],
        primary_color: str,
        secondary_color: str,
        accent_color: Optional[str],
        content_type: ContentType,
        content_strategy: ContentStrategy,
        platforms: str,
        logo_bytes: Optional[bytes],
        start_date: Optional[str],
        end_date: Optional[str],
        posting_frequency: Optional[str],
        product_name: Optional[str],
        product_description: Optional[str],
        product_price: Optional[str],
        product_sku: Optional[str],
        product_category: Optional[str],
        product_subcategory: Optional[str],
        product_tags: Optional[str],
        product_features: Optional[str],
        product_benefits: Optional[str],
        product_image_url: Optional[str],
        product_image_data: Optional[dict],
        product_post_percentage: Optional[int],
        service_name: Optional[str],
        service_description: Optional[str],
        service_price: Optional[str],
        service_duration: Optional[str],
        service_category: Optional[str],
        service_subcategory: Optional[str],
        service_tags: Optional[str],
        service_features: Optional[str],
        service_benefits: Optional[str],
        service_image_url: Optional[str],
        service_image_data: Optional[dict],
        service_post_percentage: Optional[int],
        primary_font: Optional[str] = None,
        secondary_font: Optional[str] = None,
        accent_font: Optional[str] = None,
        custom_prompt: Optional[str] = None,
    ):
        """Run full campaign generation in background; push progress events to queue."""

        campaign_id = job_id

        logger.info("=" * 70)
        logger.info(f"[ADVANCED CAMPAIGN] {campaign_name}")
        logger.info(f" ID: {campaign_id}")
        logger.info(f" Company: {company_name}")
        logger.info(f" Website: {website or 'N/A'}")
        logger.info(f" Goal: {campaign_goal.value}")
        logger.info(f" Posts requested: {num_posts}")
        logger.info("=" * 70)

        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(_campaign_heartbeat(job_id, queue, heartbeat_stop))

        try:
            color_payload = build_brand_payload(
                primary_color=primary_color,
                secondary_color=secondary_color,
                accent_color=accent_color,
                primary_font=primary_font,
                secondary_font=secondary_font,
                accent_font=accent_font,
            )

            # ═══════════════════════════════════════════════════════════════
            # STEP 1: VALIDATE PLATFORMS
            # ═══════════════════════════════════════════════════════════════
            platform_list = [p.strip().lower() for p in platforms.split(',') if p.strip()]
            valid_platforms = [p for p in platform_list if p in CAMPAIGN_PLATFORM_SPECS]

            if not valid_platforms:
                raise HTTPException(
                    status_code=400,
                    detail=f"No valid platforms. Choose from: {list(CAMPAIGN_PLATFORM_SPECS.keys())}"
                )

            logger.info(f" Platforms: {', '.join(valid_platforms)}")

            _started_event = {
                "step": "started",
                "message": f"Generating campaign \"{campaign_name}\" for {company_name}",
                "campaign_id": campaign_id,
                "total_posts": num_posts,
                "platforms": valid_platforms,
            }
            await queue.put(_started_event)
            _append_event(job_id, _started_event)

            # ═══════════════════════════════════════════════════════════════
            # STEP 2: PARSE PRODUCTS AND SERVICES FROM INDIVIDUAL FIELDS
            # ═══════════════════════════════════════════════════════════════
            items_to_promote = []

            # Helper function to parse pipe-separated fields
            def parse_pipe_list(field_str: Optional[str]) -> List[str]:
                if not field_str:
                    return []
                return [item.strip() for item in field_str.split('|') if item.strip()]

            # ═══════════════════════════════════════════════════════════════
            # PROCESS SINGLE PRODUCT (Simplified)
            # ═══════════════════════════════════════════════════════════════
            processed_product_image = None

            if product_name and product_name.strip():
                logger.info(f"\n   [PRODUCT] Processing: {product_name}")

                # Product image already processed in POST handler — use passed data
                processed_product_image = product_image_data
                if processed_product_image and processed_product_image.get("success"):
                    logger.info(f"      [OK] Product image provided")

                # Parse tags, features, benefits (pipe-separated)
                tags = parse_pipe_list(product_tags)
                features = parse_pipe_list(product_features)
                benefits = parse_pipe_list(product_benefits)

                items_to_promote.append({
                    "type": "product",
                    "name": product_name.strip(),
                    "description": product_description,
                    "price": product_price,
                    "sku": product_sku,
                    "category": product_category,
                    "subcategory": product_subcategory,
                    "tags": tags,
                    "features": features,
                    "benefits": benefits,
                    "image_url": product_image_url,
                    "uploaded_image_data": processed_product_image,
                    "post_percentage": product_post_percentage or 0,
                })

                has_img = "[IMG]" if (processed_product_image or product_image_url) else ""
                logger.info(f"      Product: {product_name} | {product_post_percentage or 0}% allocation {has_img}")

            # ═══════════════════════════════════════════════════════════════
            # PROCESS SINGLE SERVICE (Simplified)
            # ═══════════════════════════════════════════════════════════════
            processed_service_image = None

            if service_name and service_name.strip():
                logger.info(f"\n   [SERVICE] Processing: {service_name}")

                # Service image already processed in POST handler — use passed data
                processed_service_image = service_image_data
                if processed_service_image and processed_service_image.get("success"):
                    logger.info(f"      [OK] Service image provided")

                # Parse tags, features, benefits (pipe-separated)
                tags = parse_pipe_list(service_tags)
                features = parse_pipe_list(service_features)
                benefits = parse_pipe_list(service_benefits)

                items_to_promote.append({
                    "type": "service",
                    "name": service_name.strip(),
                    "description": service_description,
                    "price": service_price,
                    "duration": service_duration,
                    "category": service_category,
                    "subcategory": service_subcategory,
                    "tags": tags,
                    "features": features,
                    "benefits": benefits,
                    "image_url": service_image_url,
                    "uploaded_image_data": processed_service_image,
                    "post_percentage": service_post_percentage or 0,
                })

                has_img = "[IMG]" if (processed_service_image or service_image_url) else ""
                logger.info(f"      Service: {service_name} | {service_post_percentage or 0}% allocation {has_img}")

            # ═══════════════════════════════════════════════════════════════
            # SMART CAMPAIGN DISTRIBUTION LOGIC
            # ═══════════════════════════════════════════════════════════════
            # Calculate: Product % + Service % + Remaining % for Company/Brand
            # Example: 10 posts, Product=40%, Service=40% → 4+4=8, Company gets 2
            product_pct = product_post_percentage or 0
            service_pct = service_post_percentage or 0
            total_specified = product_pct + service_pct
            company_pct = max(0, 100 - total_specified)

            logger.info(f"\n   [DISTRIBUTION] Campaign allocation:")
            logger.info(f"      Product:  {product_pct}%")
            logger.info(f"      Service:  {service_pct}%")
            logger.info(f"      Company:  {company_pct}% (remaining)")

            # Add company/brand item for remaining percentage
            if company_pct > 0:
                items_to_promote.append({
                    "type": "brand",
                    "name": company_name,
                    "description": company_description or f"{company_name} - Excellence in everything we do",
                    "price": None,
                    "category": "Brand Awareness",
                    "tags": ["brand", "company", "awareness"],
                    "features": [],
                    "benefits": [],
                    "image_url": None,
                    "uploaded_image_data": None,
                    "post_percentage": company_pct,
                })
                logger.info(f"      Brand item added: {company_name} | {company_pct}%")

            # ═══════════════════════════════════════════════════════════════
            # NEW: Hybrid Smart Company Understanding (Option C)
            # ═══════════════════════════════════════════════════════════════
            if not items_to_promote:
                logger.info(f"\n   [SMART] No products/services provided - using HYBRID SMART UNDERSTANDING")
                logger.info(f"      Strategy: Web scraping + Gemini fallback + Combined insights")
                
                try:
                    # Use hybrid approach: web scraping + Gemini knowledge
                    company_analysis = await hybrid_company_understanding(
                        gemini_client=gemini_client,
                        gemini_model=CAMPAIGN_TEXT_MODEL,
                        company_name=company_name,
                        company_description=company_description or f"Company: {company_name}",
                        website=website or "",
                        tagline=tagline or "N/A",
                        brand_voice=brand_voice
                    )
                    
                    logger.info(f"   [ANALYSIS] Analysis complete - Data source: {company_analysis.get('data_source', 'unknown')}")
                    logger.info(f"   [INDUSTRY] Industry: {company_analysis.get('industry', 'Unknown')}")
                    logger.info(f"   [MODEL] Business Model: {company_analysis.get('business_model', 'Unknown')}")
                    
                    # Generate campaign items from analysis
                    items_to_promote = generate_brand_awareness_items(
                        analysis=company_analysis,
                        company_name=company_name
                    )
                    
                    logger.info(f"   [OK] Generated {len(items_to_promote)} brand awareness items")
                    
                except Exception as e:
                    logger.error(f"   [ERROR] Hybrid company understanding failed: {e}")
                    logger.error(traceback.format_exc())
                    
                    # Fallback: Create single brand item
                    logger.info(f"   [FALLBACK] Using fallback: Single brand awareness item")
                    
                    items_to_promote = [{
                        "type": "brand_theme",
                        "name": company_name,
                        "description": company_description or f"{company_name} - Your trusted partner",
                        "category": "Brand Awareness",
                        "tags": ["brand", "awareness"],
                        "price": None,
                        "post_percentage": 100,
                    }]


            # ═══════════════════════════════════════════════════════════════
            # STEP 3: BUILD GENERATION QUEUE (PERCENTAGE-BASED)
            # ═══════════════════════════════════════════════════════════════
            logger.info(f"\n   Building generation queue (percentage-based)...")

            # Calculate post count per item based on post percentage
            generation_queue = []

            for item in items_to_promote:
                post_percentage = item.get('post_percentage', 100.0 / len(items_to_promote))
                posts_for_item = max(1, round(num_posts * (post_percentage / 100.0)))
                item['posts_count'] = posts_for_item

                logger.info(f"      {item['name']}: {posts_for_item} posts ({post_percentage}% of {num_posts})")

                # Add this item to generation queue multiple times
                for _ in range(posts_for_item):
                    generation_queue.append({"item": item})

            # Adjust if we exceeded num_posts due to rounding
            if len(generation_queue) > num_posts:
                generation_queue = generation_queue[:num_posts]
            elif len(generation_queue) < num_posts:
                # Add extra posts, cycling through items
                remaining = num_posts - len(generation_queue)
                for i in range(remaining):
                    item = items_to_promote[i % len(items_to_promote)]
                    generation_queue.append({"item": item})

            logger.info(f" Total queue items: {len(generation_queue)} (will generate {len(generation_queue)} posts)")

            # ═══════════════════════════════════════════════════════════════
            # STEP 4: DISTRIBUTE ACROSS PLATFORMS
            # ═══════════════════════════════════════════════════════════════
            for i, task in enumerate(generation_queue):
                platform = valid_platforms[i % len(valid_platforms)]
                task['platform'] = platform
                task['post_number'] = i + 1

            # STEP 5: logo_bytes received as parameter — no file reading needed

            # ═══════════════════════════════════════════════════════════════
            # STEP 6: GENERATE POSTS (PARALLEL WITH SEMAPHORE)
            # ═══════════════════════════════════════════════════════════════
            CONCURRENCY_LIMIT = 5  # Max concurrent Gemini API calls
            semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
            total_tasks = len(generation_queue)


            async def _generate_single_post(task):
                """Generate a single campaign post (image + caption) with concurrency control."""
                async with semaphore:
                    post_num = task["post_number"]
                    item = task["item"]
                    platform = task["platform"]
                    platform_spec = CAMPAIGN_PLATFORM_SPECS[platform]

                    item_type = item["type"]
                    item_name = item["name"]

                    logger.info(f"\n   [{post_num}/{total_tasks}] {item_type.upper()}: {item_name} on {platform.upper()}")

                    # ── Resolve reference image ──────────────────────────────────────────────
                    product_ref_image = None
                    if item.get("uploaded_image_data") and item["uploaded_image_data"].get("success"):
                        logger.info(f"      [REF_IMAGE] Using uploaded product image...")
                        product_ref_image = item["uploaded_image_data"]
                    elif item.get("image_url"):
                        logger.info(f"      [REF_IMAGE] Downloading product reference image from URL...")
                        product_ref_image = await asyncio.to_thread(download_reference_image, item["image_url"])
                        if not (product_ref_image and product_ref_image.get("success")):
                            logger.warning(f"      [REF_IMAGE] Download failed — proceeding without reference")
                            product_ref_image = None

                    _has_ref_image = bool(product_ref_image and product_ref_image.get("success"))
                    _item_desc = item.get('description', '')[:500] if item.get('description') else f'Premium {item_type} from {company_name}'
                    _visual_approach = _get_visual_approach(item_type, campaign_goal.value, item_name)

                    # When a reference image is provided, override the visual approach for both
                    # product and service so Gemini is explicitly anchored to the provided photo —
                    # not inventing the product/environment from scratch.
                    if _has_ref_image and item_type.lower() == "product":
                        _visual_approach = (
                            f"SELECTED APPROACH → REFERENCE-ANCHORED PRODUCT HERO\n"
                            f"⚠ A reference image has been provided immediately above. It shows the ACTUAL product: '{item_name}'.\n"
                            f"MANDATORY: Your generated image MUST feature this exact product — same shape, same colors, same material finish, same proportions.\n"
                            f"• The viewer must be able to RECOGNISE this as the identical product from the reference photo\n"
                            f"• Do NOT invent, hallucinate, or redesign the product — use what is shown in the reference\n"
                            f"• Place it in an aspirational lifestyle context that amplifies its quality and desirability\n"
                            f"• The product is the undisputed hero — dominant in the frame, fully visible, never cropped at any edge"
                        )
                    elif _has_ref_image and item_type.lower() == "service":
                        _visual_approach = (
                            f"SELECTED APPROACH → REFERENCE-GROUNDED ENVIRONMENT\n"
                            f"⚠ A reference image has been provided immediately above. It shows the ACTUAL space, environment, or setting for '{item_name}'.\n"
                            f"MANDATORY: Your generated image MUST be visually grounded in that reference photo — same space, same atmosphere, same architectural identity, same materials and lighting character.\n"
                            f"• Reproduce the real environment faithfully — do NOT replace it with a generic, hallucinated, or stock-photo alternative\n"
                            f"• You may enrich the scene: add people interacting naturally, improve lighting dramatics, heighten the emotional resonance\n"
                            f"• The reference environment is the story — keep it recognisable and authentic"
                        )

                    _promoting_line = f"{item_type.title()} — {item_name}"

                    # ===================================================================
                    # BUILD IMAGE PROMPT (Gemini renders text + photo together)
                    # ===================================================================
                    _logo_instruction = (
                        "Integrate the brand logo (shown above) as a natural design element — place it in a compositionally clean zone where it feels purposefully designed in, not pasted on. The surrounding area must harmonize with the logo's own colors and style. PIXEL-PERFECT LOGO REPRODUCTION: The logo is a locked identity asset — do NOT recolor, restyle, reinterpret, redesign, or alter ANY element (colors, fonts, shapes, icons, arrangement). Every color in the logo must appear exactly as provided. Only resize/scale the logo as needed for placement — absolutely no other changes."
                        if logo_bytes else "No logo provided — do not invent or hallucinate any brand mark."
                    )
                    _post_pct = item.get('post_percentage', 100)
                    _visual_weight = (
                        f"Visual Emphasis: {_post_pct}% of this campaign is allocated to {item_type} '{item_name}' — this image must give DOMINANT visual weight and creative focus to this {item_type}. It is the HERO of this image."
                        if _post_pct >= 50 else
                        f"Visual Emphasis: {_post_pct}% campaign allocation — the {item_type} '{item_name}' should be clearly featured but can share visual space with brand identity elements."
                    )
                    _color_ref = color_payload["atmosphere_reference"]

                    _PLATFORM_VISUAL_TREATMENT = {
                        "instagram": "Aspirational lifestyle, high editorial punch — saturated but tasteful, thumb-stopping contrast. Every pixel must earn the scroll-stop.",
                        "facebook":  "Human, warm, community-rooted — relatable over polished. Approachable warmth and real emotions that invite sharing.",
                        "linkedin":  "Professional authority and clean confidence — architectural precision, credible people, ample white space. Signals expertise without trying too hard.",
                        "twitter":   "Graphic impact at thumbnail scale — maximum contrast, bold silhouettes, minimal visual complexity. Reads in 0.3 seconds.",
                        "youtube":   "Cinematic scope and drama — wide, immersive, motion-suggesting. Scale, emotion, and narrative energy.",
                    }
                    _platform_vt = _PLATFORM_VISUAL_TREATMENT.get(platform, f"Platform-appropriate visual treatment for {platform}.")

                    # ── STEP A: Generate caption + display_text ──────────────────────────────
                    logger.info(f"      [STEP A] Generating caption + display_text...")
                    caption, hashtags, campaign_display_text = await generate_caption_and_hashtags(
                        item_name=item_name,
                        item_type=item_type,
                        item_description=item.get("description"),
                        item_price=item.get("price"),
                        platform=platform,
                        platform_spec=platform_spec,
                        company_name=company_name,
                        brand_voice=brand_voice,
                        campaign_goal=campaign_goal.value,
                        campaign_goal_direction=_get_campaign_goal_caption_direction(campaign_goal.value),
                        content_type_direction=_get_content_type_caption_direction(content_type.value),
                        gemini_client=gemini_client,
                        gemini_model=gemini_model,
                        tagline=tagline
                    )
                    logger.info(f"      [STEP A] Caption: '{caption[:50]}...' | Display: '{campaign_display_text[:50]}'")

                    if content_strategy == ContentStrategy.platform_specific:
                        prompt = f"""{SPELLING_PRIORITY_PREAMBLE}
You are a world-class creative director, art director, and visual designer with 25+ years building award-winning campaigns for global brands across every industry — luxury, technology, healthcare, finance, consumer, enterprise. You produce work that earns attention, builds brand memory, and drives results.

Read the complete brand payload and campaign brief. Then plan and generate a fully crafted marketing image — visual concept, composition, integrated typography, and logo placement — executed at agency level.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PAYLOAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company: {company_name}
Tagline: "{tagline or '—'}"
Brand Voice: {brand_voice or 'Professional and trustworthy'}
Brand Color Hierarchy:
{color_payload["prompt_block"]}
Brand Font Hierarchy:
{color_payload["font_prompt_block"]}
Website: {website or '—'}
Industry Profile: {(company_description or 'Professional services')[:350]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMPAIGN BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Promoting: {_promoting_line}
What it is: {_item_desc}
Goal: {campaign_goal.value.upper()} — {_get_goal_focus(campaign_goal.value)}
Emotional Hook: {_get_emotional_hook(campaign_goal.value)}
Content Type: {content_type.value.upper()} — {_get_content_type_image_direction(content_type.value)}
{_visual_weight}
Platform: {platform_spec['name']} | Format: 4:5 | Tone: {platform_spec['tone']}
Platform Visual Language: {_platform_vt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ STEP 1 — VISUAL APPROACH
{_visual_approach}

▸ STEP 2 — COMPOSITION & ATMOSPHERE
Plan the focal point and spatial zones. The {_color_ref} is the emotional backbone of this image — dominant scene colors, lighting, materials, surfaces, and reflections MUST embody this color hierarchy. They must feel like they live IN the scene, not applied over it. Camera angle and depth of field must reflect the brand's market tier and campaign emotion.
SPATIAL RULES — establish these before placing any element:
— Product/subject visibility: the ENTIRE product must be fully within frame with intentional breathing space on all sides. Never crop any edge of the product at the canvas boundary — partial or edge-clipped products are a failure.
— Text zone: plan a dedicated text zone before arranging any visual element — product anchors one side, text zone occupies the opposing side or the lower third. The text zone is designed in from the start, not found in leftover space afterward.
{f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S VISUAL CONCEPT — THIS OVERRIDES THE DEFAULT BRIEF BELOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{custom_prompt}

Use this as the foundation for the scene. Adapt it to the brand payload and platform —
but preserve the core visual concept, composition, lighting approach, and emotional intent exactly as described.
''' if custom_prompt else ""}
▸ STEP 3 — TYPOGRAPHY (ART DIRECTED — NOT TEMPLATED)
The typography is a creative design decision, not a template to fill in. Choose a layout that serves THIS specific image — the weight, size, number of lines, and placement are yours to decide.
⚠ CRITICAL: Do NOT render any label words ("Headline", "Subline", "Line 1", "Line 2") — render ONLY the actual copy.
⛔ CANVAS RULE: ALL text must be 100% fully visible within the image frame — no word, letter, or character may be clipped or cut off at any edge. Size down the font or break a long line into two before ever letting text overflow the canvas boundary.
Options (choose the one that best fits the visual):
  • A single bold statement — sized to fit the full width with clear margin on both sides
  • A two-line hierarchy with a dominant headline and a supporting line, both fully within frame
  • Three short lines of equal or graduated weight for rhythm
  • A kinetic display type that runs with the composition's energy
The copy must be specific to {company_name} — no filler, no generic phrases.
Text color drawn from this image's own palette — harmonize with the brand color hierarchy led by {color_payload["primary_color"]}, never a default white or black unless the composition demands it. Apply a directional shadow matching the scene's light source.
{TYPOGRAPHY_PRECISION}

▸ STEP 4 — LOGO
{_logo_instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXECUTION STANDARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{REALISM_STANDARD}

{NEGATIVE_PROMPT}
✗ No sexual, erotic, or adult content  ✗ No violence or disturbing imagery
✗ No emojis or emoji-style graphics  ✗ No generic posed stock-photo scenes
✗ No anatomical misalignment — face direction MUST match body orientation. No twisted necks or heads facing opposite to body. No ghost-like disconnected anatomy.
{"✓ Integrate the provided brand logo (shown above) as a natural design element — surroundings must harmonize with logo colors, not clash" if logo_bytes else "✗ Do NOT invent or hallucinate any company logo or brand mark — omit entirely"}
"""
                        aspect_ratio = "3:4"
                    else:
                        prompt = f"""{SPELLING_PRIORITY_PREAMBLE}
You are a world-class creative director, art director, and visual designer with 25+ years building award-winning campaigns for global brands across every industry — luxury, technology, healthcare, finance, consumer, enterprise. You produce work that earns attention, builds brand memory, and drives results.

Read the complete brand payload and campaign brief. Then plan and generate a fully crafted marketing image — visual concept, composition, integrated typography, and logo placement — executed at agency level.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PAYLOAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company: {company_name}
Tagline: "{tagline or '—'}"
Brand Voice: {brand_voice or 'Professional and trustworthy'}
Brand Color Hierarchy:
{color_payload["prompt_block"]}
Brand Font Hierarchy:
{color_payload["font_prompt_block"]}
Website: {website or '—'}
Industry Profile: {(company_description or 'Professional services')[:350]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMPAIGN BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Promoting: {_promoting_line}
What it is: {_item_desc}
Goal: {campaign_goal.value.upper()} — {_get_goal_focus(campaign_goal.value)}
Emotional Hook: {_get_emotional_hook(campaign_goal.value)}
Content Type: {content_type.value.upper()} — {_get_content_type_image_direction(content_type.value)}
{_visual_weight}
Platform: Multi-platform ({', '.join(valid_platforms)}) | Format: Square 1:1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ STEP 1 — VISUAL APPROACH
{_visual_approach}

▸ STEP 2 — COMPOSITION & ATMOSPHERE
Plan the focal point and spatial zones. The {_color_ref} is the emotional backbone of this image — dominant scene colors, lighting, materials, surfaces, and reflections MUST embody this color hierarchy. They must feel like they live IN the scene, not applied over it. Square format — central focal point works across all platforms.
SPATIAL RULES — establish these before placing any element:
— Product/subject visibility: the ENTIRE product must be fully within frame with intentional breathing space on all sides. Never crop any edge of the product at the canvas boundary — partial or edge-clipped products are a failure.
— Text zone: plan a dedicated text zone before arranging any visual element — product anchors the centre, text zone occupies the lower third or a clear side panel. The text zone is designed in from the start, not found in leftover space afterward.
{f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S VISUAL CONCEPT — THIS OVERRIDES THE DEFAULT BRIEF BELOW
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{custom_prompt}

Use this as the foundation for the scene. Adapt it to the brand payload and platform —
but preserve the core visual concept, composition, lighting approach, and emotional intent exactly as described.
''' if custom_prompt else ""}
▸ STEP 3 — TYPOGRAPHY (ART DIRECTED — NOT TEMPLATED)
The typography is a creative design decision, not a template to fill in. Choose a layout that serves THIS specific image — the weight, size, number of lines, and placement are yours to decide.
⚠ CRITICAL: Do NOT render any label words ("Headline", "Subline", "Line 1", "Line 2") — render ONLY the actual copy.
⛔ CANVAS RULE: ALL text must be 100% fully visible within the image frame — no word, letter, or character may be clipped or cut off at any edge. Size down the font or break a long line into two before ever letting text overflow the canvas boundary.
Options (choose the one that best fits the visual):
  • A single bold statement — sized to fit the full width with clear margin on both sides
  • A two-line hierarchy with a dominant headline and a supporting line, both fully within frame
  • Three short lines of equal or graduated weight for rhythm
  • A kinetic display type that runs with the composition's energy
The copy must be specific to {company_name} — no filler, no generic phrases.
Text color drawn from this image's own palette — harmonize with the brand color hierarchy led by {color_payload["primary_color"]}, never a default white or black unless the composition demands it. Apply a directional shadow matching the scene's light source.
{TYPOGRAPHY_PRECISION}

▸ STEP 4 — LOGO
{_logo_instruction}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXECUTION STANDARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{REALISM_STANDARD}

{NEGATIVE_PROMPT}
✗ No sexual, erotic, or adult content  ✗ No violence or disturbing imagery
✗ No emojis or emoji-style graphics  ✗ No generic posed stock-photo scenes
✗ No anatomical misalignment — face direction MUST match body orientation. No twisted necks or heads facing opposite to body. No ghost-like disconnected anatomy.
{"✓ Integrate the provided brand logo (shown above) as a natural design element — surroundings must harmonize with logo colors, not clash" if logo_bytes else "✗ Do NOT invent or hallucinate any company logo or brand mark — omit entirely"}
"""
                        aspect_ratio = "1:1"

                    try:
                        # ── Build Gemini contents as a SINGLE multimodal user turn ──────────────
                        # Critical: all parts (reference image, prompt, logo) must live inside ONE
                        # types.Content(role="user", parts=[...]).  A flat list makes each element
                        # a separate conversation turn — the model can't associate the reference
                        # image with the generation task.  All image data must be raw bytes;
                        # passing a base64 string causes silent decode failure in the SDK.
                        _parts = []

                        # 1. Reference image FIRST — raw bytes via typed Blob
                        if _has_ref_image:
                            product_context = build_product_image_context(
                                reference_image=product_ref_image,
                                item_name=item_name,
                                item_type=item_type
                            )
                            # product_context = [{"inline_data": {"mime_type":..., "data": bytes}}, "text"]
                            _ref_inline = product_context[0]["inline_data"]
                            _parts.append(types.Part(
                                inline_data=types.Blob(
                                    mime_type=_ref_inline["mime_type"],
                                    data=_ref_inline["data"]          # raw bytes
                                )
                            ))
                            _parts.append(types.Part(text=product_context[1]))
                            logger.info(f"      [REF_IMAGE] ✓ Reference image injected as typed Part with raw bytes")
                        elif item.get("uploaded_image_data") or item.get("image_url"):
                            logger.warning(f"      [REF_IMAGE] Could not process image — proceeding without reference")

                        # 2. Main generation prompt
                        _parts.append(types.Part(text=prompt))

                        # 3. Logo — raw bytes via typed Blob
                        if logo_bytes:
                            _logo_mime = "image/jpeg" if logo_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                            _parts.append(types.Part(
                                inline_data=types.Blob(mime_type=_logo_mime, data=logo_bytes)
                            ))
                            _parts.append(types.Part(text=(
                                "THIS IMAGE IS THE BRAND LOGO — MEMORISE ITS EXACT COLORS RIGHT NOW.\n"
                                "Look at every color in this logo carefully. You must reproduce each one with zero deviation.\n\n"
                                "THE LOGO IS A FLAT 2D ASSET — NOT A SCENE OBJECT:\n"
                                "It does not exist inside the photograph or render. It is not lit by the scene's light.\n"
                                "It is composited ON TOP of the finished image — like a logo on a printed poster.\n"
                                "The scene's warm glow, cool shadows, and color grade DO NOT reach the logo. It is immune.\n\n"
                                "ONLY ALLOWED: resize or scale the logo to fit its placement zone.\n\n"
                                "FORBIDDEN — each of these is an immediate, unrecoverable failure:\n"
                                "✗ Any color change — even 1% shift in hue, saturation, or brightness\n"
                                "✗ Tinting or warming the logo to match the scene's light (the most common mistake — do not do this)\n"
                                "✗ Desaturating, darkening, or lightening any logo color\n"
                                "✗ Changing any shape, font, icon, line weight, or spacing inside the logo\n"
                                "✗ Removing, adding, or moving any element inside the logo\n"
                                "✗ Cropping or clipping any part of the logo\n\n"
                                "FINAL COLOR CHECK: Before outputting the image, compare the logo you rendered to this reference. "
                                "If any color differs — fix it before output. The logo must look identical to this image, just resized."
                            )))

                        # Single user turn containing all parts
                        contents = [types.Content(role="user", parts=_parts)]

                        # STEP B: Generate image
                        image_response = await gemini_client.aio.models.generate_content(
                            model=image_model,
                            contents=contents,
                            config=types.GenerateContentConfig(
                                temperature=0.75,
                                response_modalities=["IMAGE"],
                                image_config=types.ImageConfig(
                                    aspect_ratio=aspect_ratio
                                )
                            )
                        )

                        # Log token usage
                        usage = getattr(image_response, 'usage_metadata', None)
                        if usage:
                            logger.info(f"Image_Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

                        # Extract image
                        image_bytes = None
                        if (not image_response.candidates or
                            not image_response.candidates[0].content or
                            not image_response.candidates[0].content.parts):
                            logger.error(f"      [ERROR] Image generation returned empty/blocked response for post {post_num}")
                            return None
                        for part in image_response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                image_bytes = part.inline_data.data
                                break

                        if not image_bytes:
                            logger.error(f"      [ERROR] No image generated for post {post_num}")
                            return None

                        # Resize to target canvas — dimensions matched to Gemini's generated ratio
                        # platform_specific uses aspect_ratio="3:4" → output 1080×1350 (direct resize, no crop)
                        # same_content uses aspect_ratio="1:1"      → output 1080×1080 (exact match, no distortion)
                        _out_w = 1080
                        _out_h = 1350 if aspect_ratio == "3:4" else 1080
                        image_bytes = resize_image_for_platform(image_bytes, _out_w, _out_h)

                        # Save image
                        save_result = save_campaign_image(
                            image_bytes=image_bytes,
                            campaign_id=campaign_id,
                            campaign_name=campaign_name,
                            platform=platform,
                            item_name=item_name,
                            post_number=post_num,
                            storage_dir=storage_dir
                        )

                        # Create preview
                        image_preview = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"

                        # SAVE COMPREHENSIVE METADATA JSON
                        metadata_content = {
                            "campaign_id": campaign_id,
                            "campaign_name": campaign_name,
                            "campaign_goal": campaign_goal.value,
                            "post_number": post_num,
                            "total_posts": total_tasks,
                            "platform": platform,
                            "item_type": item_type,
                            "item_name": item_name,
                            "item_description": item.get("description"),
                            "item_price": item.get("price"),
                            "item_sku": item.get("sku"),
                            "item_category": item.get("category"),
                            "item_subcategory": item.get("subcategory"),
                            "item_tags": item.get("tags"),
                            "item_duration": item.get("duration"),
                            "item_features": item.get("features"),
                            "item_benefits": item.get("benefits"),
                            "item_required_skills": item.get("required_skills"),
                            "post_percentage": item.get("post_percentage"),
                            "company_name": company_name,
                            "company_description": company_description,
                            "website": website,
                            "tagline": tagline,
                            "brand_voice": brand_voice,
                            "primary_color": color_payload["primary_color"],
                            "secondary_color": color_payload["secondary_color"],
                            "accent_color": color_payload["accent_color"],
                            "primary_font": color_payload["primary_font"],
                            "secondary_font": color_payload["secondary_font"],
                            "accent_font": color_payload["accent_font"],
                            "content_type": content_type.value,
                            "content_strategy": content_strategy.value,
                            "platforms_in_campaign": valid_platforms,
                            "aspect_ratio": "4:5" if aspect_ratio == "3:4" else "1:1",
                            "dimensions": f"{_out_w}x{_out_h}",
                            "file_size_bytes": len(image_bytes),
                            "model": image_model,
                            "caption": caption,
                            "hashtags": hashtags,
                            "display_text": campaign_display_text,
                            "text_rendered_by_gemini": True,
                            "generated_at": datetime.now().isoformat(),
                            "local_path": save_result["local_path"],
                            "image_url": save_result["url"],
                            "logo_included": logo_bytes is not None,
                            "reference_image_provided": _has_ref_image,
                            "reference_image_source": (
                                "upload" if (item.get("uploaded_image_data") and item["uploaded_image_data"].get("success"))
                                else "url" if item.get("image_url")
                                else None
                            ),
                            "reference_image_url": item.get("image_url") if (not item.get("uploaded_image_data") and item.get("image_url")) else None,
                            "platform_specs": {
                                "name": platform_spec['name'],
                                "tone": platform_spec['tone'],
                                "caption_style": platform_spec['caption_style']
                            }
                        }

                        image_path = Path(save_result["local_path"])
                        metadata_file = image_path.with_suffix('.json')
                        with open(metadata_file, 'w', encoding='utf-8') as f:
                            json.dump(metadata_content, f, indent=2, ensure_ascii=False)

                        logger.info(f"      [METADATA] {metadata_file.name}")

                        # Convert aspect_ratio (e.g., "3:4") to display format ("4:5")
                        _display_ratio = "4:5" if aspect_ratio == "3:4" else "1:1"
                        _display_dims = f"{_out_w}x{_out_h}"

                        post = GeneratedPost(
                            post_number=post_num,
                            platform=platform,
                            item_type=item_type,
                            item_name=item_name,
                            image_url=save_result["url"],
                            image_preview=image_preview,
                            layered=None,
                            caption=caption,
                            hashtags=hashtags,
                            aspect_ratio=_display_ratio,
                            dimensions=_display_dims,
                            metadata={
                                "campaign_id": campaign_id,
                                "content_strategy": content_strategy.value,
                                "generated_at": datetime.now().isoformat(),
                                "local_path": save_result["local_path"],
                                "metadata_file": str(metadata_file),
                                "post_percentage": item.get("post_percentage")
                            }
                        )

                        logger.info(f"      Generated: {save_result['url']}")
                        return post

                    except Exception as e:
                        logger.error(f"      [ERROR] Post {post_num} failed: {e}")
                        logger.error(traceback.format_exc())
                        return None

            # ── Atomic counter so messages always arrive 1st, 2nd, 3rd... ──
            # regardless of which image finishes first in parallel execution
            _completed_count = 0
            _counter_lock = asyncio.Lock()

            async def _post_and_notify(task):
                nonlocal _completed_count
                result = await _generate_single_post(task)
                if result:
                    async with _counter_lock:
                        _completed_count += 1
                        seq = _completed_count
                    _image_done_event = {
                        "step": "image_done",
                        "message": f"Preparing {_ordinal(seq)} image",
                        "post_number": task["post_number"],
                        "sequence": seq,
                        "total": total_tasks,
                        "image_url": result.image_url,
                        "platform": task["platform"],
                        "item_name": task["item"]["name"],
                    }
                    await queue.put(_image_done_event)
                    _append_event(job_id, _image_done_event)
                return result

            # Launch all posts in parallel (semaphore limits concurrency)
            logger.info(f"\n   [PARALLEL] Launching {total_tasks} posts with concurrency limit {CONCURRENCY_LIMIT}...")
            _generating_event = {
                "step": "generating",
                "message": f"Preparing {total_tasks} image{'s' if total_tasks > 1 else ''} for your campaign...",
                "total_posts": total_tasks,
            }
            await queue.put(_generating_event)
            _append_event(job_id, _generating_event)
            results = await asyncio.gather(
                *[_post_and_notify(task) for task in generation_queue],
                return_exceptions=True
            )

            # Collect successful results, filter out failures
            generated_posts: List[GeneratedPost] = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"      [ERROR] Post {i+1} raised exception: {result}")
                elif result is not None:
                    generated_posts.append(result)
                else:
                    logger.warning(f"      [WARN] Post {i+1} returned None (no image generated)")

            # Sort by post number to maintain order
            generated_posts.sort(key=lambda p: p.post_number)

            # ═══════════════════════════════════════════════════════════════
            # STEP 7: BUILD RESPONSE
            # ═══════════════════════════════════════════════════════════════

            # Get campaign folder path
            if generated_posts:
                campaign_folder_path = generated_posts[0].metadata.get("local_path", "")
                campaign_folder_path = str(Path(campaign_folder_path).parent) if campaign_folder_path else ""
            else:
                sanitized_name = re.sub(r'[^\w\s-]', '', campaign_name.lower())
                sanitized_name = re.sub(r'[-\s]+', '_', sanitized_name)[:30]
                campaign_folder_path = str(storage_dir / "campaigns" / f"{campaign_id[:8]}_{sanitized_name}")

            logger.info(f"\n{'=' * 70}")
            logger.info(f"ADVANCED CAMPAIGN COMPLETE: {len(generated_posts)}/{num_posts} posts")
            logger.info(f"Campaign: {campaign_name}")
            logger.info(f"Company: {company_name}")
            logger.info(f"Folder: {campaign_folder_path}")
            logger.info(f"{'=' * 70}")

            campaign_response = CampaignResponse(
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                campaign_goal=campaign_goal.value,
                content_strategy=content_strategy.value,
                campaign_folder=campaign_folder_path,
                total_posts_requested=num_posts,
                total_posts_generated=len(generated_posts),
                generated_posts=generated_posts,
                schedule_info={
                    "start_date": start_date,
                    "end_date": end_date,
                    "posting_frequency": posting_frequency
                },
                generation_summary={
                    "products_count": len([i for i in items_to_promote if i["type"] == "product"]),
                    "services_count": len([i for i in items_to_promote if i["type"] == "service"]),
                    "platforms_used": valid_platforms,
                    "company": company_name,
                    "website": website,
                    "tagline": tagline,
                    "brand_voice": brand_voice,
                    "primary_color": color_payload["primary_color"],
                    "secondary_color": color_payload["secondary_color"],
                    "accent_color": color_payload["accent_color"],
                    "logo_included": logo_bytes is not None,
                    "post_percentage_summary": {
                        item['name']: {
                            "type": item['type'],
                            "post_percentage": item['post_percentage'],
                            "posts_generated": item.get('posts_count', 0)
                        }
                        for item in items_to_promote
                    }
                }
            )
            _result_dict = campaign_response.model_dump()
            campaign_job_store[job_id]["status"] = "done"
            campaign_job_store[job_id]["result"] = _result_dict
            _persist_job(job_id, {"status": "done", "result": _result_dict})
            await _stop_background_task(heartbeat_task, heartbeat_stop)
            _done_event = {"step": "done", "message": "Completed", "result": _result_dict}
            await queue.put(_done_event)
            _append_event(job_id, _done_event)
            asyncio.create_task(_cleanup_job(job_id))

        except (Exception, asyncio.CancelledError) as e:
            logger.error(f"[ERROR] Campaign job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
            campaign_job_store[job_id]["status"] = "error"
            campaign_job_store[job_id]["error"] = str(e)
            _persist_job(job_id, {"status": "error", "error": str(e)})
            await _stop_background_task(heartbeat_task, heartbeat_stop)
            _error_event = {
                "step": "error",
                "message": "Campaign generation failed. Please try again.",
                "error": str(e),
            }
            await queue.put(_error_event)
            _append_event(job_id, _error_event)
            asyncio.create_task(_cleanup_job(job_id))

    # ═══════════════════════════════════════════════════════════════════════════
    # [ADVANCED] NEW ADVANCED ENDPOINT: Multi-Product/Service Campaign with Individual Fields
    # ═══════════════════════════════════════════════════════════════════════════
    @router.post("/create-campaign-advanced")
    async def create_campaign_advanced(
        # === CAMPAIGN SETUP ===
        campaign_name: str = Form(..., description="Name of the campaign"),
        campaign_goal: CampaignGoal = Form(..., description="Primary goal of campaign"),
        num_posts: int = Form(1, ge=1, le=50, description="Number of posts to generate (1-50)"),

        # === COMPANY/BRAND INFO ===
        company_name: str = Form(..., description="Company name"),
        company_description: Optional[str] = Form(None, description="Brief company description"),
        website: Optional[str] = Form(None, description="Company website URL"),
        tagline: Optional[str] = Form(None, description="Company tagline"),
        brand_voice: Optional[str] = Form(None, description="Brand voice/tone"),
        primary_color: str = Form(..., description="Main background / base color. Used for backgrounds, big sections, and overall feel. Can be a color name or hex code."),
        secondary_color: str = Form(..., description="Supporting color used for layout parts, boxes, cards, and dividers. Can be a color name or hex code."),
        accent_color: Optional[str] = Form(None, description="Highlight / attention color for offers, key words, and CTA emphasis. Can be a color name or hex code."),
        primary_font: Optional[str] = Form(None, description="Primary font for main headlines and core messages. Make it large, bold, and highly prominent."),
        secondary_font: Optional[str] = Form(None, description="Secondary font for supporting content like subheadings or descriptions. Keep it clean, readable, and balanced."),
        accent_font: Optional[str] = Form(None, description="Accent font for highlights, CTAs, and attention-grabbing phrases. Use it sparingly."),

        # === CONTENT SETTINGS ===
        content_type: ContentType = Form(ContentType.promotional, description="Type of content"),
        content_strategy: ContentStrategy = Form(ContentStrategy.platform_specific, description="Same design or unique per platform"),
        platforms: str = Form("instagram,facebook,linkedin", description="Comma-separated platforms"),
        logo_file: Optional[UploadFile] = File(None, description="Company logo (PNG, JPG) — upload file"),
        logo_url: Optional[str] = Form(None, description="Public URL of company logo (PNG, JPG) — used when not uploading a file"),

        # === SCHEDULING ===
        start_date: Optional[str] = Form(None),
        end_date: Optional[str] = Form(None),
        posting_frequency: Optional[str] = Form("daily"),

        # === PRODUCT FIELDS (Single Product) ===
        product_name: Optional[str] = Form(None, description="Product name"),
        product_description: Optional[str] = Form(None, description="Product description"),
        product_price: Optional[str] = Form(None, description="Product price (e.g., ₹999, $49.99)"),
        product_sku: Optional[str] = Form(None, description="Product SKU/ID"),
        product_category: Optional[str] = Form(None, description="Product category"),
        product_subcategory: Optional[str] = Form(None, description="Product subcategory"),
        product_tags: Optional[str] = Form(None, description="Product tags (pipe-separated: tag1|tag2|tag3)"),
        product_features: Optional[str] = Form(None, description="Key product features (pipe-separated: feature1|feature2)"),
        product_benefits: Optional[str] = Form(None, description="Key product benefits (pipe-separated: benefit1|benefit2)"),
        product_image_url: Optional[str] = Form(None, description="Product image URL (alternative to file upload)"),
        product_image_file: Optional[UploadFile] = File(None, description="Product image file for AI reference"),
        product_post_percentage: Optional[int] = Form(None, ge=0, le=100, description="Percentage of posts for this product (0-100)"),

        # === SERVICE FIELDS (Single Service) ===
        service_name: Optional[str] = Form(None, description="Service name"),
        service_description: Optional[str] = Form(None, description="Service description"),
        service_price: Optional[str] = Form(None, description="Service price (e.g., ₹500/hr, $99/month)"),
        service_duration: Optional[str] = Form(None, description="Service duration (e.g., 1 hour, 30 days)"),
        service_category: Optional[str] = Form(None, description="Service category"),
        service_subcategory: Optional[str] = Form(None, description="Service subcategory"),
        service_tags: Optional[str] = Form(None, description="Service tags (pipe-separated: tag1|tag2|tag3)"),
        service_features: Optional[str] = Form(None, description="Key service features (pipe-separated: feature1|feature2)"),
        service_benefits: Optional[str] = Form(None, description="Key service benefits (pipe-separated: benefit1|benefit2)"),
        service_image_url: Optional[str] = Form(None, description="Service image URL (alternative to file upload)"),
        service_image_file: Optional[UploadFile] = File(None, description="Service image file for AI reference"),
        service_post_percentage: Optional[int] = Form(None, ge=0, le=100, description="Percentage of posts for this service (0-100)"),

        # === CREATIVE DIRECTION (from Prompt Enhancer) ===
        custom_prompt: Optional[str] = Form(None, description="Visual creative direction from the prompt enhancer — the scene concept, composition, light, and style. Overrides the default creative direction for every image in this campaign."),
    ):
        """Accepts multipart form, reads files eagerly, fires background job, returns job_id immediately."""
        # Read all UploadFile objects eagerly — they can only be read once
        logo_bytes: Optional[bytes] = None
        if logo_file and logo_file.filename:
            logo_bytes = await logo_file.read()
            logger.info(f" Logo uploaded: {len(logo_bytes)} bytes")
        elif logo_url and logo_url.strip():
            try:
                import requests as _req
                _r = await asyncio.to_thread(_req.get, logo_url.strip(), timeout=15)
                if _r.status_code == 200 and _r.content:
                    logo_bytes = _r.content
                    logger.info(f" Logo fetched from URL: {logo_url} ({len(logo_bytes)} bytes)")
                else:
                    logger.warning(f" Failed to fetch logo from URL: status {_r.status_code}")
            except Exception as _e:
                logger.warning(f" Failed to fetch logo from URL: {_e}")

        product_image_data: Optional[dict] = None
        if product_image_file and product_image_file.filename:
            try:
                file_content = await product_image_file.read()
                product_image_data = process_uploaded_reference_image(file_content, product_image_file.filename)
                if not (product_image_data and product_image_data.get("success")):
                    logger.warning(f" Product image failed to process")
                    product_image_data = None
                else:
                    logger.info(f" Product image uploaded: {product_image_file.filename}")
            except Exception as e:
                logger.warning(f" Product image error: {e}")

        service_image_data: Optional[dict] = None
        if service_image_file and service_image_file.filename:
            try:
                file_content = await service_image_file.read()
                service_image_data = process_uploaded_reference_image(file_content, service_image_file.filename)
                if not (service_image_data and service_image_data.get("success")):
                    logger.warning(f" Service image failed to process")
                    service_image_data = None
                else:
                    logger.info(f" Service image uploaded: {service_image_file.filename}")
            except Exception as e:
                logger.warning(f" Service image error: {e}")

        job_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        campaign_job_store[job_id] = {"status": "processing", "queue": queue}
        # Persist immediately so other instances/workers can detect this job
        _persist_job(job_id, {"status": "processing"})
        logger.info(f"[WS] Campaign job created: {job_id}  campaign='{campaign_name}'")

        asyncio.create_task(_run_campaign_job(
            job_id=job_id,
            queue=queue,
            campaign_name=campaign_name,
            campaign_goal=campaign_goal,
            num_posts=num_posts,
            company_name=company_name,
            company_description=company_description,
            website=website,
            tagline=tagline,
            brand_voice=brand_voice,
            primary_color=primary_color,
            secondary_color=secondary_color,
            accent_color=accent_color,
            primary_font=primary_font,
            secondary_font=secondary_font,
            accent_font=accent_font,
            content_type=content_type,
            content_strategy=content_strategy,
            platforms=platforms,
            logo_bytes=logo_bytes,
            start_date=start_date,
            end_date=end_date,
            posting_frequency=posting_frequency,
            product_name=product_name,
            product_description=product_description,
            product_price=product_price,
            product_sku=product_sku,
            product_category=product_category,
            product_subcategory=product_subcategory,
            product_tags=product_tags,
            product_features=product_features,
            product_benefits=product_benefits,
            product_image_url=product_image_url,
            product_image_data=product_image_data,
            product_post_percentage=product_post_percentage,
            service_name=service_name,
            service_description=service_description,
            service_price=service_price,
            service_duration=service_duration,
            service_category=service_category,
            service_subcategory=service_subcategory,
            service_tags=service_tags,
            service_features=service_features,
            service_benefits=service_benefits,
            service_image_url=service_image_url,
            service_image_data=service_image_data,
            service_post_percentage=service_post_percentage,
            custom_prompt=custom_prompt,
        ))

        return {
            "job_id": job_id,
            "status": "processing",
            "message": f"Campaign '{campaign_name}' started. Connect to /ws/campaign/{job_id} for real-time progress.",
        }


    # ═══════════════════════════════════════════════════════════════════════════
    # WEBSOCKET — real-time campaign progress stream
    # ═══════════════════════════════════════════════════════════════════════════
    @router.websocket("/ws/campaign/{job_id}")
    async def ws_campaign_status(websocket: WebSocket, job_id: str):
        """
        Stream campaign generation progress.

        Messages pushed by the server (every message includes a human-readable "message" field):
          {"step": "started",    "message": "...", "campaign_id": ..., "total_posts": N, "platforms": [...]}
          {"step": "generating", "message": "...", "total_posts": N}
          {"step": "image_done", "message": "...", "post_number": N, "total": N, "image_url": "...", "platform": "...", "item_name": "..."}
          {"step": "done",       "message": "...", "result": { full CampaignResponse dict }}
          {"step": "error",      "message": "...", "error": "...details..."}
        """
        await websocket.accept()

        # Wait briefly for the job to be registered (race between POST return and WS connect)
        for _ in range(20):
            if job_id in campaign_job_store:
                break
            await asyncio.sleep(0.15)

        if job_id not in campaign_job_store:
            # Check file — handles reconnects AND cross-instance jobs
            saved = _read_persisted_job(job_id)
            if saved and saved.get("status") == "done":
                await websocket.send_json({"step": "done", "message": "Completed", "result": saved["result"]})
                await websocket.close(code=1000)
            elif saved and saved.get("status") == "error":
                await websocket.send_json({"step": "error", "message": "Campaign generation failed.", "error": saved.get("error", "Unknown error")})
                await websocket.close(code=1000)
            elif saved and saved.get("status") == "processing":
                # Job is running on a different instance — stream events from shared disk file
                logger.info(f"[WS] Cross-instance job detected {job_id}, switching to file-poll mode")
                events_file = _campaign_jobs_dir / f"_job_{job_id}.events.jsonl"
                cursor = 0
                try:
                    while True:
                        if events_file.exists():
                            lines = events_file.read_text(encoding="utf-8").splitlines()
                            for line in lines[cursor:]:
                                line = line.strip()
                                if not line:
                                    continue
                                event = json.loads(line)
                                await websocket.send_json(event)
                                cursor += 1
                                if event.get("step") in ("done", "error"):
                                    await websocket.close(code=1000)
                                    return
                        await asyncio.sleep(0.5)
                except WebSocketDisconnect:
                    logger.info(f"[WS] Client disconnected from cross-instance job {job_id}")
                finally:
                    try:
                        await websocket.close(code=1000)
                    except Exception:
                        pass
            else:
                await websocket.send_json({"step": "error", "error": f"Invalid job_id: {job_id}"})
                await websocket.close(code=1008)
            return

        queue: asyncio.Queue = campaign_job_store[job_id]["queue"]
        try:
            while True:
                message = await queue.get()
                await websocket.send_json(message)
                if message.get("step") in ("done", "error"):
                    break
        except WebSocketDisconnect:
            logger.info(f"[WS] Client disconnected from job {job_id}")
        finally:
            try:
                await websocket.close(code=1000)
            except Exception:
                pass



    # ═══════════════════════════════════════════════════════════════════════════
    # [SMART MODE] WIZARD-STYLE POST CREATION API
    # ═══════════════════════════════════════════════════════════════════════════

    return router