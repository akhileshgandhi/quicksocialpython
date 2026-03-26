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
    resize_image_for_platform,
)
from prompt_guards import NEGATIVE_PROMPT, TYPOGRAPHY_PRECISION, REALISM_STANDARD, SPELLING_PRIORITY_PREAMBLE

logger = logging.getLogger(__name__)


def create_campaign_router(gemini_client, gemini_model, image_model, storage_dir):
    router = APIRouter(tags=["Campaign"])
    campaign_job_store: Dict[str, dict] = {}

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

    def _read_persisted_job(job_id: str) -> Optional[dict]:
        try:
            f = _campaign_jobs_dir / f"_job_{job_id}.json"
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _ordinal(n: int) -> str:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
        return f"{n}{suffix}"

    def _get_goal_focus(goal: str) -> str:
        """Return design focus based on campaign goal"""
        goal_mapping = {
            "Brand awareness": "Introduce brand personality, showcase company values, build emotional connection, make it memorable",
            "Lead generation": "Highlight unique value proposition, create curiosity, emphasize benefits, encourage contact/signup",
            "Sales & conversion": "Emphasize transformation and ROI, create urgency with limited offers, show social proof, strong value messaging",
            "Engagement": "Tell compelling stories, ask engaging questions, encourage shares and comments, build community feeling",
            "Customer retention": "Show appreciation for loyalty, highlight exclusive benefits, create sense of belonging, recognize customer achievements"
        }
        return goal_mapping.get(goal, "Highlight product/service value and quality")
    
    def _get_emotional_hook(goal: str) -> str:
        """Return emotional hook based on campaign goal"""
        goal_mapping = {
            "Brand awareness": "CURIOSITY - Make them want to know more about this brand",
            "Lead generation": "INTEREST - Create desire to learn more and take action",
            "Sales & conversion": "DESIRE + URGENCY - Make them want to buy NOW",
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
            ("brand",   "Brand awareness"):     ("GRAPHIC DESIGN COMP.",     f"'{_n}' as pure design statement — signature color, bold typography, iconic geometry. No product needed. The brand IS the image."),
            ("brand",   "Sales & conversion"):  ("EDITORIAL LIFESTYLE",      f"'{_n}' in action — aspirational lifestyle imagery people want to buy into. Brand as identity and desire."),
            ("brand",   "Lead generation"):     ("ARCHITECTURAL/ENVIRON.",   f"The '{_n}' brand world — the aesthetic universe this brand inhabits. Credibility and aspiration through environment."),
            ("brand",   "Engagement"):          ("CULTURAL/FESTIVE MOMENT",  f"'{_n}' as community — celebrate the shared identity and culture this brand represents. Make the audience feel they belong."),
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
        return f"SELECTED APPROACH → GRAPHIC DESIGN COMP.\n'{_n}' brand personality expressed through bold design, color, and typography."

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
        brand_colors: Optional[str],
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

        try:
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

            await queue.put({
                "step": "started",
                "message": f"Generating campaign \"{campaign_name}\" for {company_name}",
                "campaign_id": campaign_id,
                "total_posts": num_posts,
                "platforms": valid_platforms,
            })

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

                    # ===================================================================
                    # BUILD IMAGE PROMPT (Gemini renders text + photo together)
                    # ===================================================================
                    _logo_instruction = (
                        "Integrate the brand logo (shown above) as a natural design element — place it in a compositionally clean zone where it feels purposefully designed in, not pasted on. The surrounding area must harmonize with the logo's own colors and style. PIXEL-PERFECT LOGO REPRODUCTION: The logo is a locked identity asset — do NOT recolor, restyle, reinterpret, redesign, or alter ANY element (colors, fonts, shapes, icons, arrangement). Every color in the logo must appear exactly as provided. Only resize/scale the logo as needed for placement — absolutely no other changes."
                        if logo_bytes else "No logo provided — do not invent or hallucinate any brand mark."
                    )
                    _item_desc = item.get('description', '')[:500] if item.get('description') else f'Premium {item_type} from {company_name}'
                    _post_pct = item.get('post_percentage', 100)
                    _visual_weight = (
                        f"Visual Emphasis: {_post_pct}% of this campaign is allocated to {item_type} '{item_name}' — this image must give DOMINANT visual weight and creative focus to this {item_type}. It is the HERO of this image."
                        if _post_pct >= 50 else
                        f"Visual Emphasis: {_post_pct}% campaign allocation — the {item_type} '{item_name}' should be clearly featured but can share visual space with brand identity elements."
                    )
                    _visual_approach = _get_visual_approach(item_type, campaign_goal.value, item_name)
                    _font_style = _get_font_style(brand_voice or '')
                    _color_ref = brand_colors or 'the brand color palette'

                    # ── Per-post creative angle (cycles through 8 universal approaches) ──
                    # Zero extra API calls. The image model derives the specific scene
                    # from the brand payload + this angle directive.
                    _CREATIVE_ANGLES = [
                        ("HUMAN IMPACT",
                         f"Show a real person whose situation is genuinely changed by {item_name}. "
                         f"Make the transformation specific and visible — not symbolic. Real setting, "
                         f"real expression, the result evident in the scene."),
                        ("PROOF OF RESULTS",
                         f"Make the measurable outcome the visual hero. A real result that {item_name} delivers — "
                         f"a metric on a real screen, a concrete before/after state, a clear win. Evidence over promise."),
                        ("BRAND AUTHORITY",
                         f"Express {company_name}'s identity and expertise directly — bold, confident, minimal. "
                         f"The brand's voice and values as the image itself, without relying on the product alone."),
                        ("THE PROBLEM",
                         f"Show the real frustration or gap that {item_name} solves. The audience should "
                         f"recognise their own situation immediately — honest, grounded, relatable, real."),
                        ("TRUST & CRAFT",
                         f"Show the people, process, or depth of expertise behind {company_name}. "
                         f"The quality of thought and work that makes {item_name} worth choosing."),
                        ("ASPIRATION",
                         f"Show the outcome the brand enables — the state of work or life that becomes "
                         f"possible with {item_name}. Real, grounded, genuinely desirable."),
                        ("ONE SPECIFIC DETAIL",
                         f"Zoom in on one concrete, specific aspect of {item_name} — one feature, one use case, "
                         f"one moment of use — explored with precision and depth. Specificity over breadth."),
                        ("SOCIAL PROOF",
                         f"Let real results speak — real reviews, real numbers, real client moments. "
                         f"The evidence that {item_name} delivers, shown rather than claimed."),
                    ]
                    _angle_name, _angle_desc = _CREATIVE_ANGLES[(post_num - 1) % len(_CREATIVE_ANGLES)]

                    # ── Composition directive (cycles through 8 physically distinct layouts) ──
                    # All platforms now share the same 4:5 format, so explicit composition
                    # rotation is the ONLY way to guarantee structural variety across posts.
                    _COMPOSITION_DIRECTIVES = [
                        ("ISOLATED HERO",
                         f"CENTER-FRAME ISOLATION: The {item_type} is perfectly centered. "
                         f"Ultra-clean, minimal background — a single material surface or pure graduated tone. "
                         f"Maximum breathing space on all four sides. No competing visual elements. "
                         f"The {item_type} elevated to the status of a gallery sculpture. Tight depth of field."),

                        ("SUBJECT RIGHT — TEXT LEFT",
                         f"ASYMMETRIC RIGHT ANCHOR: The {item_type} anchors the RIGHT third of frame. "
                         f"The LEFT two-thirds is intentional, high-contrast negative space — "
                         f"a clean open void designed to hold the headline. "
                         f"Camera at eye level. Shallow depth of field softens background."),

                        ("OVERHEAD FLAT-LAY",
                         f"TOP-DOWN BIRD'S-EYE: Camera directly overhead, 90-degree angle looking straight down. "
                         f"The {item_type} arranged on a textured horizontal surface with 2-3 carefully chosen props. "
                         f"Open space in the upper-left corner reserved for text overlay. "
                         f"All elements seen from directly above — pure graphic, no perspective depth."),

                        ("MACRO CLOSE-UP — TEXTURE",
                         f"EXTREME CLOSE-UP: Camera so close that only ONE portion of the {item_type} fills the frame — "
                         f"a surface texture, material edge, or defining physical detail. "
                         f"The subject becomes abstract and desire-inducing at this scale. "
                         f"Intentionally cropped at frame edges. Upper third held open for text."),

                        ("ENVIRONMENTAL WIDE SHOT",
                         f"SCENE OVER SUBJECT: Pull back. The {item_type} occupies no more than 25% of the frame — "
                         f"the environment, location, and context dominate. "
                         f"This post sells the world the {item_type} lives in, not the {item_type} alone. "
                         f"Open sky or clean architectural element in the upper area holds space for text."),

                        ("LOW ANGLE — UPWARD PERSPECTIVE",
                         f"HEROIC UPWARD CAMERA: Camera positioned LOW, shooting UP toward the {item_type} or its user. "
                         f"Sky, ceiling, or dramatic environment fills the top half of frame. "
                         f"The subject appears monumental and aspirational from below. "
                         f"Put the upper half of the canvas to dramatic, wide-open use."),

                        ("SUBJECT LEFT — TEXT RIGHT",
                         f"ASYMMETRIC LEFT ANCHOR: Mirror of the right-anchor layout. The {item_type} anchors the LEFT third. "
                         f"The RIGHT two-thirds is open negative space ready for copy. "
                         f"Alternating left-right across posts keeps the campaign grid visually dynamic. "
                         f"Slight downward angle. Sharp subject, soft background."),

                        ("DIAGONAL ENERGY",
                         f"DIAGONAL AXIS COMPOSITION: The primary subject or its dominant lines run along the diagonal "
                         f"of the frame — lower-left to upper-right or upper-left to lower-right. "
                         f"Strong sense of motion, tension, or forward momentum. "
                         f"Unconventional cropping at frame edges. Text in the calmer opposing corner."),
                    ]
                    _comp_name, _comp_instruction = _COMPOSITION_DIRECTIVES[(post_num - 1) % len(_COMPOSITION_DIRECTIVES)]

                    # ── Platform visual treatment (differentiates platforms despite same format) ──
                    _PLATFORM_VISUAL_TREATMENT = {
                        "instagram": "Aspirational lifestyle, high editorial punch — saturated but tasteful, thumb-stopping contrast. Every pixel must earn the scroll-stop.",
                        "facebook":  "Human, warm, community-rooted — relatable over polished. Approachable warmth and real emotions that invite sharing.",
                        "linkedin":  "Professional authority and clean confidence — architectural precision, credible people, ample white space. Signals expertise without trying too hard.",
                        "twitter":   "Graphic impact at thumbnail scale — maximum contrast, bold silhouettes, minimal visual complexity. Reads in 0.3 seconds.",
                        "youtube":   "Cinematic scope and drama — wide, immersive, motion-suggesting. Scale, emotion, and narrative energy.",
                    }
                    _platform_vt = _PLATFORM_VISUAL_TREATMENT.get(platform, f"Platform-appropriate visual treatment for {platform}.")

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
Brand Colors: {brand_colors or 'Industry-appropriate palette'}
Website: {website or '—'}
Industry Profile: {company_description or 'Professional services'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMPAIGN BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Promoting: {item_type.title()} — {item_name}
What it is: {_item_desc}
Goal: {campaign_goal.value.upper()} — {_get_goal_focus(campaign_goal.value)}
Emotional Hook: {_get_emotional_hook(campaign_goal.value)}
Content Type: {content_type.value.upper()} — {_get_content_type_image_direction(content_type.value)}
{_visual_weight}
Platform: {platform_spec['name']} | Format: {platform_spec['aspect_ratio']} | Tone: {platform_spec['tone']}
Platform Visual Language: {_platform_vt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ STEP 1 — VISUAL CONCEPT

READ THE FULL BRAND PAYLOAD AND CAMPAIGN BRIEF ABOVE BEFORE PROCEEDING.

This image is post {post_num} of {total_tasks} in {company_name}'s campaign.
It must feel like it was commissioned and approved by {company_name}'s own marketing team —
not AI-generated, not a template, not a stock photo concept.

CREATIVE DIRECTION: {_visual_approach}
{f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S VISUAL CONCEPT — PRIMARY CREATIVE BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{custom_prompt}

This is the user's chosen creative direction. Use it as the foundation for the scene
concept. Adapt it to the brand payload, the product being promoted, and the platform —
but preserve the core visual concept, composition, lighting approach, and emotional
intent exactly as described.
''' if custom_prompt else ""}
THIS POST'S ANGLE — {_angle_name}:
{_angle_desc}

BEFORE YOU RENDER ANYTHING — MAKE THESE THREE DECISIONS:

① SCENE (most important):
{f"Build directly on the USER'S VISUAL CONCEPT above — adapt it for [{_angle_name}] applied to {item_name} on {platform_spec['name']}. Keep the visual language, composition, lighting approach, and emotional tone from the user's brief intact." if custom_prompt else f"What single, specific, real-world scene — one that could actually be photographed or professionally rendered by a human creative team — best delivers [{_angle_name}] for {company_name}'s audience? Draw this scene from the brand payload above: the company description, brand voice, the item being promoted, and its actual details. Be concrete and specific — not a category of image but a precise visual moment."}
✗ If your scene could apply to ANY company in this space — reject it and think again.
✗ If the scene relies on abstract metaphors instead of real-world grounding — reject it.

② BRAND DNA:
Does the scene reflect '{brand_voice or 'the brand voice'}' and the brand colors
not as labels but as lived qualities — present in the lighting, materials, setting,
energy, and the people or objects shown?

③ COMPOSITION DIRECTIVE — {_comp_name} (MANDATORY):
{_comp_instruction}
This is a hard structural requirement. Execute it precisely — it is not a suggestion.

④ VISUAL DISTINCTION:
Post {post_num} of {total_tasks} — if all {total_tasks} posts in this campaign were laid side by side, this one must be IMMEDIATELY distinguishable from every other. The composition above is already different. Beyond that: use a different lighting setup, a different scene location, a different color temperature, and a different relationship between subject and environment than the adjacent posts. Same brand, same quality — totally different image.

▸ STEP 2 — COMPOSITION & ATMOSPHERE
Plan the focal point and spatial zones. The {_color_ref} is the emotional backbone of this image — dominant scene colors, lighting, materials, surfaces, and reflections MUST embody these brand colors. They must feel like they live IN the scene, not applied over it. Camera angle and depth of field must reflect the brand's market tier and campaign emotion.
SPATIAL RULES — establish these before placing any element:
— Product/subject visibility: the ENTIRE product must be fully within frame with intentional breathing space on all sides. Never crop any edge of the product at the canvas boundary — partial or edge-clipped products are a failure.
— Text zone: plan a dedicated text zone before arranging any visual element — product anchors one side, text zone occupies the opposing side or the lower third. The text zone is designed in from the start, not found in leftover space afterward.

▸ STEP 3 — TYPOGRAPHY (DESIGNED INTO THE IMAGE, NOT PLACED ON TOP)
Design the typography as a native element of this composition — the font, color, placement, shadow, and weight must feel like they were conceived alongside the visual, not applied after. The text must belong to this image.
Render exactly TWO lines of marketing copy directly on the image.
⚠ CRITICAL: Do NOT render the words "Headline", "Subline", "Line 1", "Line 2", or any label — render ONLY the actual marketing copy text itself.
  — Line 1 (bold, large): Primary message — short and punchy headline, no filler
  — Line 2 (lighter weight, smaller): Supporting message — clear and complete, no padding
Font: {_font_style}
Text color drawn from this image's own palette — harmonize with {_color_ref}, never a default white or black unless the composition demands it. Apply a directional shadow matching the scene's light source.
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
                        aspect_ratio = platform_spec['gemini_aspect']
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
Brand Colors: {brand_colors or 'Industry-appropriate palette'}
Website: {website or '—'}
Industry Profile: {company_description or 'Professional services'}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CAMPAIGN BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Promoting: {item_type.title()} — {item_name}
What it is: {_item_desc}
Goal: {campaign_goal.value.upper()} — {_get_goal_focus(campaign_goal.value)}
Emotional Hook: {_get_emotional_hook(campaign_goal.value)}
Content Type: {content_type.value.upper()} — {_get_content_type_image_direction(content_type.value)}
{_visual_weight}
Platform: Multi-platform ({', '.join(valid_platforms)}) | Format: 4:5 Portrait | Current: {platform_spec['name']}
Platform Visual Language: {_platform_vt}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ STEP 1 — VISUAL CONCEPT

READ THE FULL BRAND PAYLOAD AND CAMPAIGN BRIEF ABOVE BEFORE PROCEEDING.

This image is post {post_num} of {total_tasks} in {company_name}'s campaign.
It must feel like it was commissioned and approved by {company_name}'s own marketing team —
not AI-generated, not a template, not a stock photo concept.

CREATIVE DIRECTION: {_visual_approach}
{f'''
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USER'S VISUAL CONCEPT — PRIMARY CREATIVE BRIEF
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{custom_prompt}

This is the user's chosen creative direction. Use it as the foundation for the scene
concept. Adapt it to the brand payload, the product being promoted, and the platform —
but preserve the core visual concept, composition, lighting approach, and emotional
intent exactly as described.
''' if custom_prompt else ""}
THIS POST'S ANGLE — {_angle_name}:
{_angle_desc}

BEFORE YOU RENDER ANYTHING — MAKE THESE THREE DECISIONS:

① SCENE (most important):
{f"Build directly on the USER'S VISUAL CONCEPT above — adapt it for [{_angle_name}] applied to {item_name} on {platform_spec['name']}. Keep the visual language, composition, lighting approach, and emotional tone from the user's brief intact." if custom_prompt else f"What single, specific, real-world scene — one that could actually be photographed or professionally rendered by a human creative team — best delivers [{_angle_name}] for {company_name}'s audience? Draw this scene from the brand payload above: the company description, brand voice, the item being promoted, and its actual details. Be concrete and specific — not a category of image but a precise visual moment."}
✗ If your scene could apply to ANY company in this space — reject it and think again.
✗ If the scene relies on abstract metaphors instead of real-world grounding — reject it.

② BRAND DNA:
Does the scene reflect '{brand_voice or 'the brand voice'}' and the brand colors
not as labels but as lived qualities — present in the lighting, materials, setting,
energy, and the people or objects shown?

③ COMPOSITION DIRECTIVE — {_comp_name} (MANDATORY):
{_comp_instruction}
This is a hard structural requirement. Execute it precisely — it is not a suggestion.

④ VISUAL DISTINCTION:
Post {post_num} of {total_tasks} — if all {total_tasks} posts in this campaign were laid side by side, this one must be IMMEDIATELY distinguishable from every other. The composition above is already different. Beyond that: use a different lighting setup, a different scene location, a different color temperature, and a different relationship between subject and environment than the adjacent posts. Same brand, same quality — totally different image.

▸ STEP 2 — COMPOSITION & ATMOSPHERE
Plan the focal point and spatial zones. The {_color_ref} is the emotional backbone of this image — dominant scene colors, lighting, materials, surfaces, and reflections MUST embody these brand colors. They must feel like they live IN the scene, not applied over it. Square format — central focal point works across all platforms.
SPATIAL RULES — establish these before placing any element:
— Product/subject visibility: the ENTIRE product must be fully within frame with intentional breathing space on all sides. Never crop any edge of the product at the canvas boundary — partial or edge-clipped products are a failure.
— Text zone: plan a dedicated text zone before arranging any visual element — product anchors the centre, text zone occupies the lower third or a clear side panel. The text zone is designed in from the start, not found in leftover space afterward.

▸ STEP 3 — TYPOGRAPHY (DESIGNED INTO THE IMAGE, NOT PLACED ON TOP)
Design the typography as a native element of this composition — the font, color, placement, shadow, and weight must feel like they were conceived alongside the visual, not applied after. The text must belong to this image.
Render exactly TWO lines of marketing copy directly on the image.
⚠ CRITICAL: Do NOT render the words "Headline", "Subline", "Line 1", "Line 2", or any label — render ONLY the actual marketing copy text itself.
  — Line 1 (bold, large): Primary message — short and punchy headline, no filler
  — Line 2 (lighter weight, smaller): Supporting message — clear and complete, no padding
Font: {_font_style}
Text color drawn from this image's own palette — harmonize with {_color_ref}, never a default white or black unless the composition demands it. Apply a directional shadow matching the scene's light source.
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
                        # Build content for Gemini
                        contents = [prompt]

                        # PRODUCT/SERVICE REFERENCE IMAGE INTEGRATION
                        product_ref_image = None
                        if item.get("uploaded_image_data") and item["uploaded_image_data"].get("success"):
                            logger.info(f"      [REF_IMAGE] Using uploaded product image...")
                            product_ref_image = item["uploaded_image_data"]
                        elif item.get("image_url"):
                            logger.info(f"      [REF_IMAGE] Downloading product reference image from URL...")
                            product_ref_image = await asyncio.to_thread(download_reference_image, item["image_url"])

                        if product_ref_image and product_ref_image.get("success"):
                            product_context = build_product_image_context(
                                reference_image=product_ref_image,
                                item_name=item_name,
                                item_type=item_type
                            )
                            contents.extend(product_context)
                            logger.info(f"      [REF_IMAGE] ✓ Product reference image added to generation context")
                        elif item.get("uploaded_image_data") or item.get("image_url"):
                            logger.warning(f"      [REF_IMAGE] Could not process product image, proceeding without reference")

                        # Logo injection — send actual logo for Gemini to place in image
                        if logo_bytes:
                            _logo_mime = "image/jpeg" if logo_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                            contents.append({"inline_data": {"mime_type": _logo_mime, "data": base64.b64encode(logo_bytes).decode("utf-8")}})
                            contents.append("LOGO REFERENCE: This is the exact brand logo — treat it as a LOCKED, PIXEL-PERFECT asset. Integrate it into the composition so it feels designed in, not pasted on. ABSOLUTELY DO NOT change any logo colors, fonts, shapes, icons, or styling. Do not reinterpret or redesign any part of it. The only allowed operation is resizing/scaling. Every color in this logo must appear exactly as shown.")

                        # ═══════════════════════════════════════════════════════════
                        # STEP A: Generate caption + display_text FIRST
                        # ═══════════════════════════════════════════════════════════
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

                        # STEP D: Generate image
                        from google.genai import types
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

                        # Resize if same_content strategy
                        if content_strategy == ContentStrategy.same_content:
                            image_bytes = resize_image_for_platform(
                                image_bytes,
                                platform_spec['width'],
                                platform_spec['height']
                            )

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
                            "brand_colors": brand_colors,
                            "content_type": content_type.value,
                            "content_strategy": content_strategy.value,
                            "platforms_in_campaign": valid_platforms,
                            "aspect_ratio": platform_spec['aspect_ratio'],
                            "dimensions": f"{platform_spec['width']}x{platform_spec['height']}",
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

                        post = GeneratedPost(
                            post_number=post_num,
                            platform=platform,
                            item_type=item_type,
                            item_name=item_name,
                            image_url=save_result["url"],
                            image_preview=image_preview,
                            caption=caption,
                            hashtags=hashtags,
                            aspect_ratio=platform_spec['aspect_ratio'],
                            dimensions=f"{platform_spec['width']}x{platform_spec['height']}",
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
                    await queue.put({
                        "step": "image_done",
                        "message": f"Preparing {_ordinal(seq)} image",
                        "post_number": task["post_number"],
                        "sequence": seq,
                        "total": total_tasks,
                        "image_url": result.image_url,
                        "platform": task["platform"],
                        "item_name": task["item"]["name"],
                    })
                return result

            # Launch all posts in parallel (semaphore limits concurrency)
            logger.info(f"\n   [PARALLEL] Launching {total_tasks} posts with concurrency limit {CONCURRENCY_LIMIT}...")
            await queue.put({
                "step": "generating",
                "message": f"Preparing {total_tasks} image{'s' if total_tasks > 1 else ''} for your campaign...",
                "total_posts": total_tasks,
            })
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
                    "brand_colors": brand_colors,
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
            await queue.put({"step": "done", "message": "Completed", "result": _result_dict})
            asyncio.create_task(_cleanup_job(job_id))

        except (Exception, asyncio.CancelledError) as e:
            logger.error(f"[ERROR] Campaign job {job_id} failed: {e}")
            logger.error(traceback.format_exc())
            campaign_job_store[job_id]["status"] = "error"
            campaign_job_store[job_id]["error"] = str(e)
            _persist_job(job_id, {"status": "error", "error": str(e)})
            await queue.put({
                "step": "error",
                "message": "Campaign generation failed. Please try again.",
                "error": str(e),
            })
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
        brand_colors: Optional[str] = Form(None, description="Brand colors (e.g., 'Red and White', '#E31837, #FFFFFF'). Used to generate brand-identity-aligned images."),

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
            brand_colors=brand_colors,
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
            # Check file — handles reconnects after completion
            saved = _read_persisted_job(job_id)
            if saved and saved.get("status") == "done":
                await websocket.send_json({"step": "done", "message": "Completed", "result": saved["result"]})
                await websocket.close(code=1000)
            elif saved and saved.get("status") == "error":
                await websocket.send_json({"step": "error", "message": "Campaign generation failed.", "error": saved.get("error", "Unknown error")})
                await websocket.close(code=1000)
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