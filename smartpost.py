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
import os

from models import (
    PostingGoal, ContentGenerationMode, MediaType,
    SmartPostCaption, SmartPostImage, SmartPostResponse,
    CAMPAIGN_PLATFORM_SPECS
)
from utils import (
    extract_gemini_text, log_gemini_usage,
    download_reference_image, process_uploaded_reference_image,
)
from prompt_guards import (
    NEGATIVE_PROMPT,
    CAPTION_ENRICHMENT_DIRECTIVE,
    TYPOGRAPHY_PRECISION,
    REALISM_STANDARD,
    SPELLING_PRIORITY_PREAMBLE,
)

logger = logging.getLogger(__name__)


def _get_smartpost_visual_approach(goal_value: str, brand_voice: str = "") -> str:
    """Auto-select the best visual approach based on posting goal and brand voice"""
    v = (brand_voice or "").lower()
    approach_map = {
        "promotional":       ("PRODUCT/SERVICE HERO",    "The featured offer IS the image — present it at its most desirable. Lead with value, not decoration."),
        "engagement":        ("EDITORIAL LIFESTYLE",     "Authentic moment — real people, genuine emotion, a scene the audience recognizes and wants to join."),
        "brand awareness":   ("GRAPHIC DESIGN COMP.",    "Brand personality as pure design — signature color, bold typography, iconic geometry. The brand IS the image."),
        "educational":       ("CONCEPTUAL/ABSTRACT",     "Visual metaphor that makes the concept immediately graspable — clarity and insight over decoration."),
        "announcement":      ("GRAPHIC DESIGN COMP.",    "Bold announcement design — the news is the headline. Typography-forward, high-contrast, unmissable."),
        "testimonial":       ("EDITORIAL LIFESTYLE",     "Real person, genuine moment — humanize the testimonial with authentic photography and warm composition."),
        "festival":          ("CULTURAL/FESTIVE MOMENT", "Festival-specific visual language — cultural palette, symbols, and energy specific to this occasion only."),
        "behind the scenes": ("ARCHITECTURAL/ENVIRON.",  "Reveal the real space and process — authenticity over polish. The environment tells the story."),
        "awareness":         ("GRAPHIC DESIGN COMP.",    "Brand as pure visual statement — bold color, strong type, nothing generic."),
    }
    goal_lower = goal_value.lower()
    for key, (name, desc) in approach_map.items():
        if key in goal_lower:
            return f"SELECTED APPROACH → {name}\n{desc}"
    # Brand-voice fallback
    if any(w in v for w in ["luxury", "premium", "craft", "artisan", "heritage", "sophisticated"]):
        return "SELECTED APPROACH → MATERIAL & CRAFT DETAIL\nMacro quality and surface richness — luxury communicates itself through texture and light."
    if any(w in v for w in ["tech", "digital", "modern", "innovation", "minimal"]):
        return "SELECTED APPROACH → CONCEPTUAL/ABSTRACT\nClean visual idea — intelligent, precise, forward-looking. The concept IS the image."
    return "SELECTED APPROACH → EDITORIAL LIFESTYLE\nAuthentic, brand-true imagery that stops the scroll and communicates the goal in a genuine human moment."


def _get_smartpost_font_style(brand_voice: str) -> str:
    """Infer specific font style from brand voice"""
    if not brand_voice:
        return "Humanist sans-serif — clean, versatile, professional. Strong weight contrast between headline and subline."
    v = brand_voice.lower()
    if any(w in v for w in ["luxury", "heritage", "artisan", "premium", "classic", "elegant", "refined", "sophisticated", "craft", "couture", "bespoke", "haute", "cultural", "deep"]):
        return "HIGH-CONTRAST EDITORIAL SERIF (Didot / Bodoni style) — luxury/heritage brand. Fine hairline strokes signal craftsmanship and exclusivity. Bold headline, thin subline."
    elif any(w in v for w in ["tech", "innovation", "digital", "modern", "minimal", "clean", "precise", "futuristic", "smart", "data", "scientific"]):
        return "GEOMETRIC SANS-SERIF (Futura / Montserrat style) — modern/tech brand. Tight tracking, rational letterforms, clean uppercase headline. Signals precision and momentum."
    elif any(w in v for w in ["creative", "fashion", "lifestyle", "playful", "warm", "casual", "vibrant", "expressive", "energetic", "youthful", "bold", "dynamic", "edgy"]):
        return "EXPRESSIVE DISPLAY (Bebas Neue / Abril Fatface style) — brand with personality. Headline as a graphic element. Oversized, confident, visual attitude."
    elif any(w in v for w in ["corporate", "professional", "trust", "reliable", "authority", "expert", "institutional", "credible"]):
        return "HUMANIST SANS-SERIF (Gill Sans / Source Sans style) — approachable yet professional. Legible at all sizes. Trustworthy gravitas without being cold."
    elif any(w in v for w in ["natural", "organic", "sustainable", "earth", "eco", "wellness", "health", "mindful", "botanical"]):
        return "ORGANIC SERIF or HAND-CRAFTED style (Lora / Merriweather) — warm, grounded, connected to nature. Type that feels considered and human."
    return f"Typeface that embodies '{brand_voice}' — the font is part of the brand expression. Let the voice drive weight, spacing, and personality."


# ─────────────────────────────────────────────────────────────────────────────
# LAYER 1 — ARC DEFINITIONS (global, zero API calls)
# Each arc type defines the narrative strategy and per-slide roles
# for a globally valid carousel playbook.
# ─────────────────────────────────────────────────────────────────────────────

ARC_DEFINITIONS = {
    "problem_solution": {
        "name": "Problem → Solution",
        "description": "Identify the pain, present the fix, prove it works, drive action",
        "best_for_goals": ["Lead generation", "Sales & conversion", "Promotional"],
        "best_for_industries": ["tech", "saas", "software", "finance", "fintech", "healthcare", "medical", "legal", "insurance", "consulting", "agency", "startup", "hr", "recruitment", "crm"],
        "slide_roles": {
            2: ["PROBLEM", "SOLUTION_CTA"],
            3: ["PROBLEM", "SOLUTION", "CTA"],
            4: ["PROBLEM", "SOLUTION", "PROOF", "CTA"],
        },
        "default_slides": 4,
    },
    "desire_accumulation": {
        "name": "Desire Accumulation",
        "description": "Build desire through beauty, detail and lifestyle — make them crave it before seeing the price",
        "best_for_goals": ["Brand awareness", "Sales & conversion", "Engagement", "Promotional"],
        "best_for_industries": ["fashion", "luxury", "beauty", "cosmetic", "food", "restaurant", "lifestyle", "travel", "hotel", "hospitality", "jewellery", "jewel", "apparel", "clothing", "fragrance", "perfume", "watch"],
        "slide_roles": {
            2: ["HERO", "BRAND_STATEMENT"],
            3: ["HERO", "DETAIL", "BRAND_STATEMENT"],
            4: ["HERO", "DETAIL", "CONTEXT", "BRAND_STATEMENT"],
        },
        "default_slides": 4,
    },
    "feature_showcase": {
        "name": "Feature Showcase",
        "description": "Overview then deep-dive into each key feature or differentiator — let the product sell itself",
        "best_for_goals": ["Sales & conversion", "Lead generation", "Brand awareness", "Promotional"],
        "best_for_industries": ["product", "real estate", "property", "automotive", "car", "electronics", "gadget", "appliance", "app", "mobile", "ecommerce", "e-commerce", "retail"],
        "slide_roles": {
            2: ["OVERVIEW", "FEATURES_CTA"],
            3: ["OVERVIEW", "KEY_FEATURES", "CTA"],
            4: ["OVERVIEW", "FEATURE_1", "FEATURE_2", "CTA"],
        },
        "default_slides": 4,
    },
    "story_journey": {
        "name": "Story / Journey",
        "description": "Take the audience through a narrative arc — context, challenge, transformation, lesson",
        "best_for_goals": ["Engagement", "Brand awareness", "Lead generation"],
        "best_for_industries": ["education", "university", "coaching", "personal", "ngo", "charity", "foundation", "wellness", "fitness", "gym", "yoga", "mental health", "creator", "influencer"],
        "slide_roles": {
            2: ["CONTEXT", "TRANSFORMATION_CTA"],
            3: ["CONTEXT", "CHALLENGE", "TRANSFORMATION_CTA"],
            4: ["CONTEXT", "CHALLENGE", "TRANSFORMATION", "CTA"],
        },
        "default_slides": 4,
    },
    "listicle": {
        "name": "Tips / Listicle",
        "description": "Title card → individual insights → takeaway — high-value, highly shareable format",
        "best_for_goals": ["Engagement", "Brand awareness", "Educational"],
        "best_for_industries": ["creator", "blog", "media", "marketing", "business", "b2b", "productivity", "management", "finance tips", "health tips"],
        "slide_roles": {
            3: ["TITLE", "TIPS", "TAKEAWAY"],
            4: ["TITLE", "TIP_1", "TIP_2", "TAKEAWAY"],
        },
        "default_slides": 4,
    },
    "reveal_tease": {
        "name": "Reveal / Tease",
        "description": "Build suspense slide by slide — tease, hint, reveal, celebrate the moment",
        "best_for_goals": ["Engagement", "Brand awareness", "Announcement"],
        "best_for_industries": ["entertainment", "event", "launch", "product launch", "music", "film", "gaming", "sports", "concert"],
        "slide_roles": {
            3: ["TEASER", "PARTIAL_REVEAL", "FULL_REVEAL_CTA"],
            4: ["TEASER", "HINT", "REVEAL", "CTA"],
        },
        "default_slides": 4,
    },
    "before_after": {
        "name": "Before → After",
        "description": "Show the transformation honestly — problem state, the process, the result, the proof",
        "best_for_goals": ["Sales & conversion", "Lead generation", "Engagement"],
        "best_for_industries": ["fitness", "gym", "beauty salon", "salon", "interior", "dental", "dermatology", "renovation", "construction", "marketing agency", "weight loss", "skin care"],
        "slide_roles": {
            2: ["BEFORE", "AFTER_CTA"],
            3: ["BEFORE", "AFTER", "CTA"],
            4: ["BEFORE", "PROCESS", "AFTER", "CTA"],
        },
        "default_slides": 3,
    },
}

SLIDE_ROLE_DESCRIPTIONS = {
    # ── problem_solution roles ────────────────────────────────────────────────
    "PROBLEM":            "Full-screen pain-point opener. Text-dominant design. Name the struggle vividly and specifically — make the audience feel seen at a granular level. The visual should feel like a mirror reflecting their exact situation. No brand softening here.",
    "PAIN_POINT":         "A second, deeper layer of the same pain — a different dimension of the problem (time, money, confidence, relationships). The audience who is still swiping is highly qualified; reward them with precision. The more specific, the more resonant.",
    "SOLUTION":           "Introduce the product/service as the definitive answer. Hero visual at its most confident. Brand colors dominant. Value proposition stated with conviction — not a feature list, a clear single promise.",
    "SOLUTION_CTA":       "Introduce the solution AND drive immediate action on the same slide. Product hero + bold, urgent CTA. For 2-slide carousels this does the heavy lifting of the entire arc. Make the promise and the action unmissable.",
    "FEATURE_1":          "First key differentiator — full slide, one feature only. Visual and specific. Make the benefit tangible, not abstract. Show it in use or in context, not as a spec.",
    "FEATURE_2":          "Second key differentiator — equal visual prominence to Feature 1, but a completely different visual treatment. Same quality bar, different energy. Variety within consistency.",
    "FEATURE_3":          "Third differentiator — the depth of the product proposition is building. Could be technical, emotional, or a surprising secondary benefit. Audience should think 'I didn't know it did that.'",
    "FEATURE_4":          "Fourth differentiator — by now the product feels fully understood and deeply desirable. Reserve a surprisingly human or unexpected benefit here to sustain engagement.",
    "FEATURE_5":          "Fifth differentiator — each feature compounds into an overwhelming case. Reserve the most forward-thinking or future-facing benefit for this slot.",
    "FEATURE_6":          "Sixth differentiator — the deepest feature in the series. Often a behind-the-scenes detail, a precision craft element, or a brand value that money can't replicate.",
    "PROOF":              "Social proof — a single compelling stat, a verbatim testimonial quote, or a measurable before/after result. Trust built through evidence, not claims. The number or quote is the hero — design around it.",
    "CASE_STUDY":         "A compressed real-world proof story — name the company or person, state the problem in one line, show the result in one powerful number or image. Credibility through radical specificity.",
    "TESTIMONIAL":        "A real customer or client voice — verbatim quote displayed prominently with the person's name, title, or company. Let the proof speak without brand editorializing. Authenticity over polish.",
    "CTA":                "Final action slide. Brand identity at full strength — logo prominent, brand colors, zero distractions. One single unmissable call to action. Clean. Confident. The audience knows exactly what to do next.",
    # ── desire_accumulation roles ─────────────────────────────────────────────
    "HERO":               "The most visually stunning slide in the entire series. Product or scene at its most aspirational — elevated to an art object. Pure desire, zero information. Make them stop scrolling with beauty alone.",
    "DETAIL":             "Macro close-up of the single most exquisite craft detail — texture, material, stitch, ingredient, surface. Intimacy signals quality. One perfect detail fills the entire frame.",
    "DETAIL_1":           "First signature craft or beauty detail — up close, sensory, specific. The element that reveals quality only visible when you look closely. Visual: macro, shallow depth of field, raking light.",
    "DETAIL_2":           "Second distinct detail — different material, different angle, different quality signal. Maintains the intimacy of Detail 1 but opens a new dimension of the product's world.",
    "DETAIL_3":           "Third layer of craft — texture, process, or finishing detail that would be invisible in a standard shot. By this slide, the audience understands this brand's obsession with quality.",
    "DETAIL_4":           "The deepest, most abstract detail — the one that proves connoisseur-level craftsmanship. Borderline abstract. Reserved for ultra-premium expressions. The final desire-building image before the brand statement.",
    "LIFESTYLE":          "The brand's world made tangible — a rich, aspirational scene that shows what life looks and feels like when this brand is part of it. Product present but not dominant. Scene sells the dream.",
    "CONTEXT":            "Product in its natural, aspirational environment. Different from Lifestyle — this is specifically about use context, not general world-building. Answers 'where does this belong in my life?'",
    "CONTEXT_1":          "First use context — shows the product in its primary, most aspirational setting. Scene-led, not product-led. The brand belongs here naturally; it was not placed here.",
    "CONTEXT_2":          "Second use context — a different occasion, setting, or demographic. Expands the brand's world without diluting identity. Same quality language, new universe.",
    "SOCIAL_PROOF":       "Numbers, logos, awards, media mentions, or community scale that builds trust visually. '10,000+ customers', Vogue features, certification marks. Credibility through external validation, not brand claims.",
    "BRAND_STATEMENT":    "The closing slide. Bold typographic brand statement — the brand voice at absolute full volume. Logo integrated as a designed element, not placed. The slide IS the brand. End with conviction.",
    # ── feature_showcase roles ────────────────────────────────────────────────
    "OVERVIEW":           "The complete picture — product or service shown in full with its single core promise visible. Sets the stage, manages expectations, and earns the swipe. Confidence over complexity.",
    "KEY_FEATURES":       "Multiple features shown together in one organized visual — infographic-style, icon grid, or product detail layout. Scannable in 3 seconds. Convinces the audience the product is complete.",
    "FEATURES_CTA":       "Key features AND a CTA on the same slide — used in shorter carousels where there's no room to separate them. Dense but organized. Grid or list layout that rewards attention and drives action.",
    # ── story_journey roles ───────────────────────────────────────────────────
    "BACKSTORY":          "The origin — who this person or brand was before the story began. Sets the stakes and humanizes what follows. The more relatable the starting point, the more powerful the transformation.",
    "CHALLENGE":          "The obstacle, pain, or crisis. Honest and unpolished — do not soften it. Tension before resolution. The audience needs to feel the weight of this moment for the transformation to land.",
    "STRUGGLE":           "The ongoing cost of the challenge — what the problem took in time, money, confidence, or relationships. Specific, authentic, human. Not a dramatic moment but a sustained reality the audience recognizes.",
    "STRUGGLE_1":         "First dimension of the struggle — what the problem cost day-to-day. Relatable, detailed, real. The audience who made it this far is deeply invested in the resolution.",
    "STRUGGLE_2":         "Second dimension — a different aspect of the same challenge. Perhaps the emotional, social, or financial cost. Deepens empathy and makes the coming transformation feel fully earned.",
    "TURNING_POINT":      "The moment everything changed — a decision, an insight, or an unexpected event. Visually tense and pivotal. The audience senses the arc turning. Hope enters the frame for the first time.",
    "TRANSFORMATION":     "The result — show the change with full aspirational force. Uplifting, undeniable, earned. The after that justifies every difficult slide before it. Do not undersell this moment.",
    "TRANSFORMATION_CTA": "Transformation AND a clear call to action on the same slide — used in shorter carousels. Emotional payoff combined with invitation. The audience feels the change and is invited to join it.",
    "LESSON":             "The single transferable insight extracted from this journey — the truth the audience will screenshot and share. Typographic-forward. Timeless, actionable, wise. Ends the narrative on resonance.",
    # ── listicle roles ────────────────────────────────────────────────────────
    "TITLE":              "Bold typographic hook card. The promise or topic in large, impossible-to-miss type. If the title doesn't make them want to swipe immediately, nothing else matters. Make the payoff feel obvious and urgent.",
    "TIPS":               "2–3 tips combined on one clean, organized slide — for shorter carousels where individual tip slides are not possible. Numbered or bulleted, specific and actionable, visually light.",
    "TIP_1":              "First insight — full slide, one point only. Specific, visual where possible, immediately applicable. Should stand alone as shareable content. Earns the swipe to the next.",
    "TIP_2":              "Second insight — same visual grammar as Tip 1, new angle. Different visual treatment to maintain rhythm. Builds the sense of escalating value.",
    "TIP_3":              "Third insight — maintain the carousel's educational rhythm. Deliver the most counterintuitive or surprising tip here to re-engage any audience starting to disengage.",
    "TIP_4":              "Fourth insight — the carousel is now a trusted resource. Each tip should feel like condensed expertise that took years to learn. Build toward the most surprising.",
    "TIP_5":              "Fifth insight — challenge conventional wisdom or reframe the problem. The audience who reached this tip is highly engaged; give them something they genuinely could not have found elsewhere.",
    "TIP_6":              "Sixth insight — depth of value is now undeniable. Bold claim backed by specific proof. Reserve for an insight that makes the audience question what they thought they knew.",
    "TIP_7":              "Seventh insight — near the peak of the series. Maximum specificity and insight density. Set up the final takeaway as an inevitable, earned conclusion.",
    "TIP_8":              "Eighth insight — the deepest in the series. Most actionable, most surprising, or most emotionally resonant advice. The audience should feel transformed just by reading this slide.",
    "TAKEAWAY":           "The single most memorable line in the entire carousel — the insight or summary the audience will carry with them. Designed to be screenshotted and shared. CTA if appropriate. End with power.",
    # ── reveal_tease roles ────────────────────────────────────────────────────
    "TEASER":             "Maximum intrigue opener — reveal absolutely nothing but make not-swiping feel impossible. A fragment, a shadow, a question, a cryptic statement. Pure curiosity with zero information.",
    "HINT":               "A deliberate, half-visible clue — something can be seen or understood but context is withheld. The audience forms theories. Make them feel smart for noticing without giving them the answer.",
    "HINT_1":             "First clue — something half-seen, half-understood. The picture is barely forming. The audience is leaning forward. Withhold just enough to sustain the swipe.",
    "HINT_2":             "Second clue — slightly more revealing but the full picture is still withheld. Tension is building. The audience is now invested in finding out. Do not let them down.",
    "HINT_3":             "Third clue — the audience thinks they know but they're not certain. Maximum tension before resolution. The visual should feel tantalizingly close to revealing everything.",
    "PARTIAL_REVEAL":     "Something real is now shown — but context is still withheld. The shape or fragment generates more questions than it answers. The reveal is near; the anticipation peaks here.",
    "PARTIAL_REVEAL_1":   "First partial reveal — the audience sees something real but the complete picture is still being withheld. The fragment is more revealing than the hints. Tension peaks.",
    "PARTIAL_REVEAL_2":   "Second partial reveal — more is visible but the final reveal is still one swipe away. This is the moment of maximum tension. Make the audience feel the reveal is inevitable.",
    "BUILD_UP":           "Rising energy immediately before the reveal — visual momentum, anticipation at its peak. Every element of this slide should communicate 'something extraordinary is about to happen.'",
    "REVEAL":             "The full reveal — maximum visual impact after maximum anticipation. The payoff of every slide that came before. Celebration energy. Do not underdeliver this moment; the entire arc lives or dies here.",
    "FULL_REVEAL_CTA":    "Full reveal AND a call to action in one powerful, complete moment — used in shorter reveal carousels. Payoff and invitation combined. The audience arrives and is immediately invited to act.",
    "CELEBRATION":        "Post-reveal celebration — the audience has arrived and the reveal is complete. Joyful, triumphant, brand-proud energy. A moment to revel in what was just shared before driving action.",
    # ── before_after roles ────────────────────────────────────────────────────
    "BEFORE":             "The starting state documented honestly — real, relatable, unfiltered, specific. The audience must see themselves in this state. No softening. The more precise the 'before,' the more powerful the 'after.'",
    "PROCESS":            "The transformation in progress — one phase of the method, care, or expertise applied. Visual should communicate precision, intentionality, and craftsmanship. Builds trust in the outcome before showing it.",
    "PROCESS_1":          "First phase of the transformation process — the initial step, tool, or method. Shows the work is thorough, not surface-level. The audience understands this transformation is earned, not accidental.",
    "PROCESS_2":          "Second phase — a different stage or technique. Deepens the audience's appreciation of the expertise. Each process slide should reveal something new about the craft or methodology.",
    "PROCESS_3":          "Third phase — often the most visually impressive step. The cumulative process is now fully apparent. The audience can almost see the 'after' from here. Reserve the most striking technique for this slot.",
    "BEHIND_THE_SCENES":  "An honest view of the environment, people, or materials behind the work — the workspace, the hands, the raw ingredients. Transparency builds trust before the result is shown. Authenticity over polish.",
    "EXPERT_INSIGHT":     "A practitioner or specialist perspective — a key technical insight explained simply, a professional endorsement, or a behind-the-craft observation. Authority without arrogance. The expert elevates the brand.",
    "AFTER":              "The result, revealed in full aspirational force — clean, undeniable, transformative. Let the transformation speak entirely for itself. No copy needed beyond the result. Design it like a hero product shot.",
    "AFTER_CTA":          "The after-result AND a call to action — used in shorter before/after carousels. Transformation + invitation combined. Show the result at full emotional impact and tell the audience exactly how to get it.",
}


def _get_slide_roles(arc_key: str, n: int) -> list:
    """
    Return the ordered slide-role sequence for any arc + slide count (2–10).
    Each arc is designed as an expandable narrative — anchors are fixed,
    middle roles fill intelligently as count increases.
    Pure Python, zero API calls.
    """
    n = max(2, min(10, n))

    sequences = {
        # ── Empathy → Solution → Evidence → Action ──────────────────────────
        "problem_solution": {
            2:  ["PROBLEM", "SOLUTION_CTA"],
            3:  ["PROBLEM", "SOLUTION", "CTA"],
            4:  ["PROBLEM", "SOLUTION", "PROOF", "CTA"],
            5:  ["PROBLEM", "PAIN_POINT", "SOLUTION", "PROOF", "CTA"],
            6:  ["PROBLEM", "PAIN_POINT", "SOLUTION", "FEATURE_1", "PROOF", "CTA"],
            7:  ["PROBLEM", "PAIN_POINT", "SOLUTION", "FEATURE_1", "FEATURE_2", "PROOF", "CTA"],
            8:  ["PROBLEM", "PAIN_POINT", "SOLUTION", "FEATURE_1", "FEATURE_2", "FEATURE_3", "PROOF", "CTA"],
            9:  ["PROBLEM", "PAIN_POINT", "SOLUTION", "FEATURE_1", "FEATURE_2", "FEATURE_3", "CASE_STUDY", "PROOF", "CTA"],
            10: ["PROBLEM", "PAIN_POINT", "SOLUTION", "FEATURE_1", "FEATURE_2", "FEATURE_3", "FEATURE_4", "CASE_STUDY", "PROOF", "CTA"],
        },
        # ── Aspiration → Desire Build → Lifestyle → Brand Promise ────────────
        "desire_accumulation": {
            2:  ["HERO", "BRAND_STATEMENT"],
            3:  ["HERO", "DETAIL", "BRAND_STATEMENT"],
            4:  ["HERO", "DETAIL", "LIFESTYLE", "BRAND_STATEMENT"],
            5:  ["HERO", "DETAIL_1", "DETAIL_2", "LIFESTYLE", "BRAND_STATEMENT"],
            6:  ["HERO", "DETAIL_1", "DETAIL_2", "CONTEXT", "LIFESTYLE", "BRAND_STATEMENT"],
            7:  ["HERO", "DETAIL_1", "DETAIL_2", "DETAIL_3", "CONTEXT", "LIFESTYLE", "BRAND_STATEMENT"],
            8:  ["HERO", "DETAIL_1", "DETAIL_2", "DETAIL_3", "CONTEXT", "LIFESTYLE", "SOCIAL_PROOF", "BRAND_STATEMENT"],
            9:  ["HERO", "DETAIL_1", "DETAIL_2", "DETAIL_3", "CONTEXT_1", "CONTEXT_2", "LIFESTYLE", "SOCIAL_PROOF", "BRAND_STATEMENT"],
            10: ["HERO", "DETAIL_1", "DETAIL_2", "DETAIL_3", "DETAIL_4", "CONTEXT_1", "CONTEXT_2", "LIFESTYLE", "SOCIAL_PROOF", "BRAND_STATEMENT"],
        },
        # ── Overview → Features → Proof → Action ────────────────────────────
        "feature_showcase": {
            2:  ["OVERVIEW", "FEATURES_CTA"],
            3:  ["OVERVIEW", "KEY_FEATURES", "CTA"],
            4:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "CTA"],
            5:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "CTA"],
            6:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "PROOF", "CTA"],
            7:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "FEATURE_4", "PROOF", "CTA"],
            8:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "FEATURE_4", "FEATURE_5", "PROOF", "CTA"],
            9:  ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "FEATURE_4", "FEATURE_5", "PROOF", "TESTIMONIAL", "CTA"],
            10: ["OVERVIEW", "FEATURE_1", "FEATURE_2", "FEATURE_3", "FEATURE_4", "FEATURE_5", "FEATURE_6", "PROOF", "TESTIMONIAL", "CTA"],
        },
        # ── Context → Conflict → Struggle → Pivot → Transformation → Wisdom ──
        "story_journey": {
            2:  ["CONTEXT", "TRANSFORMATION_CTA"],
            3:  ["CONTEXT", "CHALLENGE", "TRANSFORMATION_CTA"],
            4:  ["CONTEXT", "CHALLENGE", "TRANSFORMATION", "CTA"],
            5:  ["CONTEXT", "CHALLENGE", "TURNING_POINT", "TRANSFORMATION", "CTA"],
            6:  ["CONTEXT", "CHALLENGE", "STRUGGLE", "TURNING_POINT", "TRANSFORMATION", "CTA"],
            7:  ["CONTEXT", "CHALLENGE", "STRUGGLE", "TURNING_POINT", "TRANSFORMATION", "LESSON", "CTA"],
            8:  ["CONTEXT", "BACKSTORY", "CHALLENGE", "STRUGGLE", "TURNING_POINT", "TRANSFORMATION", "LESSON", "CTA"],
            9:  ["CONTEXT", "BACKSTORY", "CHALLENGE", "STRUGGLE_1", "STRUGGLE_2", "TURNING_POINT", "TRANSFORMATION", "LESSON", "CTA"],
            10: ["CONTEXT", "BACKSTORY", "CHALLENGE", "STRUGGLE_1", "STRUGGLE_2", "TURNING_POINT", "TRANSFORMATION", "LESSON", "TESTIMONIAL", "CTA"],
        },
        # ── Hook → Insights → Takeaway ───────────────────────────────────────
        "listicle": {
            2:  ["TITLE", "TAKEAWAY"],
            3:  ["TITLE", "TIPS", "TAKEAWAY"],
            4:  ["TITLE", "TIP_1", "TIP_2", "TAKEAWAY"],
            5:  ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TAKEAWAY"],
            6:  ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TIP_4", "TAKEAWAY"],
            7:  ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TIP_4", "TIP_5", "TAKEAWAY"],
            8:  ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TIP_4", "TIP_5", "TIP_6", "TAKEAWAY"],
            9:  ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TIP_4", "TIP_5", "TIP_6", "TIP_7", "TAKEAWAY"],
            10: ["TITLE", "TIP_1", "TIP_2", "TIP_3", "TIP_4", "TIP_5", "TIP_6", "TIP_7", "TIP_8", "TAKEAWAY"],
        },
        # ── Tease → Hints → Partial Reveals → Build-Up → Payoff ─────────────
        "reveal_tease": {
            2:  ["TEASER", "FULL_REVEAL_CTA"],
            3:  ["TEASER", "PARTIAL_REVEAL", "FULL_REVEAL_CTA"],
            4:  ["TEASER", "HINT", "REVEAL", "CTA"],
            5:  ["TEASER", "HINT", "PARTIAL_REVEAL", "REVEAL", "CTA"],
            6:  ["TEASER", "HINT", "PARTIAL_REVEAL", "BUILD_UP", "REVEAL", "CTA"],
            7:  ["TEASER", "HINT_1", "HINT_2", "PARTIAL_REVEAL", "BUILD_UP", "REVEAL", "CTA"],
            8:  ["TEASER", "HINT_1", "HINT_2", "PARTIAL_REVEAL_1", "PARTIAL_REVEAL_2", "BUILD_UP", "REVEAL", "CTA"],
            9:  ["TEASER", "HINT_1", "HINT_2", "HINT_3", "PARTIAL_REVEAL_1", "PARTIAL_REVEAL_2", "BUILD_UP", "REVEAL", "CTA"],
            10: ["TEASER", "HINT_1", "HINT_2", "HINT_3", "PARTIAL_REVEAL_1", "PARTIAL_REVEAL_2", "BUILD_UP", "REVEAL", "CELEBRATION", "CTA"],
        },
        # ── Before → Process → Proof → After ────────────────────────────────
        "before_after": {
            2:  ["BEFORE", "AFTER_CTA"],
            3:  ["BEFORE", "AFTER", "CTA"],
            4:  ["BEFORE", "PROCESS", "AFTER", "CTA"],
            5:  ["BEFORE", "PROCESS_1", "PROCESS_2", "AFTER", "CTA"],
            6:  ["BEFORE", "PROCESS_1", "PROCESS_2", "PROOF", "AFTER", "CTA"],
            7:  ["BEFORE", "PROCESS_1", "PROCESS_2", "PROCESS_3", "PROOF", "AFTER", "CTA"],
            8:  ["BEFORE", "BEHIND_THE_SCENES", "PROCESS_1", "PROCESS_2", "PROCESS_3", "PROOF", "AFTER", "CTA"],
            9:  ["BEFORE", "BEHIND_THE_SCENES", "PROCESS_1", "PROCESS_2", "PROCESS_3", "PROOF", "TESTIMONIAL", "AFTER", "CTA"],
            10: ["BEFORE", "BEHIND_THE_SCENES", "PROCESS_1", "PROCESS_2", "PROCESS_3", "EXPERT_INSIGHT", "PROOF", "TESTIMONIAL", "AFTER", "CTA"],
        },
    }

    arc_sequences = sequences.get(arc_key, sequences["feature_showcase"])
    return arc_sequences.get(n, arc_sequences[max(arc_sequences.keys())])


def _select_carousel_arc(posting_goal: str, brand_voice: str, company_description: str, requested_count: int = 0) -> tuple:
    """
    Layer 1: Intelligently select the best carousel arc type.
    If requested_count is provided (≥2) it is respected directly.
    Otherwise falls back to the arc's default_slides.
    Pure Python — zero API calls.
    Returns: (arc_key, arc_def, slide_count)
    """
    desc = (company_description or "").lower()
    voice = (brand_voice or "").lower()
    goal = posting_goal.lower()
    combined = desc + " " + voice

    scores = {key: 0 for key in ARC_DEFINITIONS}
    for arc_key, arc_def in ARC_DEFINITIONS.items():
        for g in arc_def["best_for_goals"]:
            if g.lower() in goal or goal in g.lower():
                scores[arc_key] += 3
        for kw in arc_def["best_for_industries"]:
            if kw in combined:
                scores[arc_key] += 2

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        if any(w in goal for w in ["lead", "sales", "conversion", "promotional"]):
            best = "problem_solution"
        elif any(w in goal for w in ["awareness", "engagement"]):
            best = "desire_accumulation"
        elif any(w in goal for w in ["reveal", "announcement", "launch"]):
            best = "reveal_tease"
        else:
            best = "feature_showcase"

    arc_def = ARC_DEFINITIONS[best]
    if requested_count >= 2:
        slide_count = max(2, min(10, requested_count))
    else:
        slide_count = arc_def["default_slides"]

    return best, arc_def, slide_count


def create_smartpost_router(gemini_client, gemini_model, image_model, storage_dir):
    router = APIRouter(tags=["Smart Post"])

    # ─── In-memory job store for WebSocket progress streaming ────────────────
    # Structure: { job_id: { status, queue } }
    job_store: Dict[str, dict] = {}

    # File-based persistence so reconnecting clients can retrieve completed results
    _smartpost_jobs_dir = Path(storage_dir) / "smartpost_jobs"
    _smartpost_jobs_dir.mkdir(parents=True, exist_ok=True)

    def _persist_smartpost_job(job_id: str, data: dict) -> None:
        try:
            (_smartpost_jobs_dir / f"_job_{job_id}.json").write_text(
                json.dumps(data, default=str), encoding="utf-8"
            )
        except Exception:
            pass

    def _read_persisted_smartpost_job(job_id: str) -> Optional[dict]:
        try:
            f = _smartpost_jobs_dir / f"_job_{job_id}.json"
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
        return None

    def _ordinal(n: int) -> str:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n if n < 20 else n % 10, "th")
        return f"{n}{suffix}"

    async def _cleanup_smartpost_job(job_id: str, delay: int = 300):
        await asyncio.sleep(delay)
        job_store.pop(job_id, None)
        logger.info(f"[WS] Cleaned up smart post job {job_id}")

    def _get_posting_goal_context(goal: PostingGoal) -> Dict[str, str]:
        """Get context and guidelines based on posting goal"""
        goal_contexts = {
            PostingGoal.promotional: {
                "focus": "Highlight offers, discounts, product features, and value proposition",
                "tone": "Exciting, persuasive, urgency-driven",
                "visual": "Product showcase, vibrant colors, price tags, offer badges"
            },
            PostingGoal.engagement: {
                "focus": "Spark conversations, ask questions, encourage interaction",
                "tone": "Friendly, curious, relatable, community-focused",
                "visual": "Interactive elements, question marks, polls, community vibes"
            },
            PostingGoal.announcement: {
                "focus": "Share news, launches, updates, important information",
                "tone": "Exciting, informative, newsworthy, attention-grabbing",
                "visual": "Bold typography, announcement banners, new/launch badges"
            },
            PostingGoal.brand_awareness: {
                "focus": "Build brand recognition, showcase values, tell brand story",
                "tone": "Authentic, inspiring, memorable, consistent with brand identity",
                "visual": "Brand colors, logo prominent, lifestyle imagery, brand story visuals"
            },
            PostingGoal.festival_event: {
                "focus": "Celebrate occasions, festivals, events, seasonal moments",
                "tone": "Festive, celebratory, warm, culturally relevant",
                "visual": "Festival elements, celebrations, cultural motifs, seasonal decorations"
            }
        }
        return goal_contexts.get(goal, goal_contexts[PostingGoal.promotional])

    def _save_smart_post_image(
        image_bytes: bytes,
        post_id: str,
        company_name: str,
        slide_number: Optional[int] = None
    ) -> Dict[str, str]:
        """Save smart mode image to S3 (production) or local folder (fallback)"""
        now = datetime.now()

        # Create smart-posts folder: smart_posts/{post_id}_{company_name}/
        sanitized_company = re.sub(r'[^\w\s-]', '', company_name.lower())
        sanitized_company = re.sub(r'[-\s]+', '_', sanitized_company)[:30]
        post_folder = f"{post_id[:8]}_{sanitized_company}"

        # Filename
        if slide_number:
            filename = f"slide_{slide_number}.png"
        else:
            filename = f"post_image.png"

        relative_path = f"smart_posts/{post_folder}/{filename}"

        # ═══════════════════════════════════════════════════════════════
        # PRODUCTION: Upload to S3
        # ═══════════════════════════════════════════════════════════════
        # if CAMPAIGN_S3_ENABLED:
        #     s3_key = relative_path
        #     s3_result = campaign_upload_to_s3(
        #         file_bytes=image_bytes,
        #         s3_key=s3_key,
        #         content_type="image/png",
        #         metadata={"company": company_name, "post_id": post_id, "type": "smart_post"}
        #     )

        #     if s3_result.get("success"):
        #         return {
        #             "local_path": s3_key,  # S3 key as reference
        #             "url": s3_result["s3_url"],
        #             "output_folder": f"smart_posts/{post_folder}",
        #             "storage_type": "s3"
        #         }
        #     else:
        #         logger.warning(f"[S3] Upload failed, falling back to local storage")

        # # ═══════════════════════════════════════════════════════════════
        # # LOCAL STORAGE (fallback)
        # # ═══════════════════════════════════════════════════════════════
        # organized_path = storage_dir / "smart_posts" / post_folder
        # organized_path.mkdir(parents=True, exist_ok=True)

        # file_path = organized_path / filename
        # with open(file_path, "wb") as f:
        #     f.write(image_bytes)

        # return {
        #     "local_path": str(file_path),
        #     "url": f"/images/{relative_path}",
        #     "output_folder": str(organized_path),
        #     "storage_type": "local"
        # }

        # ═══════════════════════════════════════════════════════════════
        # OLD LOCAL-ONLY CODE (COMMENTED OUT)
        # ═══════════════════════════════════════════════════════════════
        # Full path: storage_dir/smart_posts/{post_folder}/
        organized_path = storage_dir / "smart_posts" / post_folder
        organized_path.mkdir(parents=True, exist_ok=True)
        
        file_path = organized_path / filename
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        
        relative_path = f"smart_posts/{post_folder}/{filename}"
        return {
            "local_path": str(file_path),
            "url": f"/images/{relative_path}",
            "output_folder": str(organized_path)
        }
    async def _generate_smart_captions(
        company_name: str,
        company_description: Optional[str],
        tagline: Optional[str],
        brand_voice: Optional[str],
        posting_goal: PostingGoal,
        content_mode: ContentGenerationMode,
        goal_context: Dict[str, str],
        festival_context: Optional[Dict[str, Any]] = None,
        tone_attributes_list: Optional[List[str]] = None,
        writing_style: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        product_name: Optional[str] = None,
        product_description: Optional[str] = None,
        product_price: Optional[str] = None,
        product_features: Optional[str] = None,
        product_benefits: Optional[str] = None,
        service_name: Optional[str] = None,
        service_description: Optional[str] = None,
        service_price: Optional[str] = None,
        service_duration: Optional[str] = None,
        service_features: Optional[str] = None,
        service_benefits: Optional[str] = None,
    ) -> list:
        """
        Generate captions for a social media post in a single AI call.

        Returns: List[SmartPostCaption] — 1 entry for single post, 3 for A/B variations.
        """

        # Determine how many captions to generate
        if content_mode == ContentGenerationMode.ab_variations:
            num_captions = 3
            variation_labels = ["Version A", "Version B", "Version C"]
        else:
            num_captions = 1
            variation_labels = [None]

        # Use direct parameters (with sensible defaults)
        effective_description = company_description or 'A professional business'
        effective_tagline = tagline
        effective_voice = brand_voice or 'Professional yet friendly'
        tone_attributes = tone_attributes_list or []

        # Build brand voice enrichment section
        brand_voice_section = ""
        if tone_attributes or writing_style:
            brand_voice_section = f"""
═══════════════════════════════════════════════════════════════════════════════
BRAND VOICE PROFILE — MATCH THIS STYLE
═══════════════════════════════════════════════════════════════════════════════
{f"Tone Attributes: {', '.join(tone_attributes)} — embody these qualities in every sentence" if tone_attributes else ""}
{f"Writing Style: {writing_style}" if writing_style else ""}
═══════════════════════════════════════════════════════════════════════════════
"""

        # Build festival-specific context if available
        festival_section = ""
        if festival_context:
            festival_section = f"""
FESTIVAL/EVENT CONTEXT (CRITICAL - MUST ALIGN WITH THIS):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Festival Name: {festival_context.get('name', 'Festival')}
Greeting: {festival_context.get('greeting', 'Happy Festival')}
Themes: {', '.join(festival_context.get('themes', []))}
Recommended Emojis: {festival_context.get('emoji', '🎉')}
Date: {festival_context.get('formatted_date', 'Upcoming')}

⚠️ CRITICAL: The caption MUST be specifically about {festival_context.get('name', 'this festival')}.
- Use the greeting "{festival_context.get('greeting', 'Happy Festival')}" in the caption
- Include festival-specific themes: {', '.join(festival_context.get('themes', [])[:3])}
- Use these emojis: {festival_context.get('emoji', '🎉')}
- DO NOT mention any other festival or occasion
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        # ── Build offerings section (product + service) ──────────────────────
        _offering_parts = []
        if product_name:
            _p_block = [f"PRODUCT — {product_name}"]
            if product_description: _p_block.append(f"  What it is: {product_description[:150]}")
            if product_price:       _p_block.append(f"  Price: {product_price}")
            _pf = ", ".join([f.strip() for f in product_features.split("|") if f.strip()]) if product_features else ""
            _pb = ", ".join([b.strip() for b in product_benefits.split("|") if b.strip()]) if product_benefits else ""
            if _pf: _p_block.append(f"  Features: {_pf[:120]}")
            if _pb: _p_block.append(f"  Benefits: {_pb[:120]}")
            _offering_parts.append("\n".join(_p_block))
        if service_name:
            _s_block = [f"SERVICE — {service_name}"]
            if service_description: _s_block.append(f"  What it is: {service_description[:150]}")
            if service_price:       _s_block.append(f"  Price: {service_price}")
            if service_duration:    _s_block.append(f"  Duration: {service_duration}")
            _sf = ", ".join([f.strip() for f in service_features.split("|") if f.strip()]) if service_features else ""
            _sb = ", ".join([b.strip() for b in service_benefits.split("|") if b.strip()]) if service_benefits else ""
            if _sf: _s_block.append(f"  Features: {_sf[:120]}")
            if _sb: _s_block.append(f"  Benefits: {_sb[:120]}")
            _offering_parts.append("\n".join(_s_block))

        _has_multi_offering = len(_offering_parts) >= 2
        offerings_section = ""
        if _offering_parts:
            _cover_rule = (
                f"\n⚠ MANDATORY — caption must market BOTH the {product_name} AND the {service_name} together. "
                f"Weave them as a complete value story — the product as the tangible take-home, the service as the experience. "
                f"Neither can be absent from the caption."
                if _has_multi_offering else
                f"\n⚠ Caption must specifically mention and market the {'product' if product_name else 'service'} above — not just the company."
            )
            offerings_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OFFERINGS TO MARKET — EVERY CAPTION MUST COVER ALL OF THESE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{chr(10).join(_offering_parts)}
{_cover_rule}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

        prompt = f"""You are an expert social media copywriter with 20 years of brand marketing experience.

Generate {num_captions} {'unique caption variations' if num_captions > 1 else 'an engaging caption'} for a social media post.

{CAPTION_ENRICHMENT_DIRECTIVE}

COMPANY INFORMATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company Name: {company_name}
Description: {effective_description[:400]}
{f"Tagline: {effective_tagline}" if effective_tagline else ""}
Brand Voice: {effective_voice}
{brand_voice_section}
POSTING GOAL: {posting_goal.value}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Focus: {goal_context['focus']}
Tone: {goal_context['tone']}
{f"User Context: {custom_prompt[:200]}" if custom_prompt else ""}
{offerings_section}{festival_section}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PART 1 — CAPTION REQUIREMENTS:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{"MULTI-OFFERING CAPTION — COMPLETE BRAND STORY STRUCTURE (MANDATORY):" if _has_multi_offering else "CAPTION STRUCTURE:"}
{f'''
Follow this EXACT narrative flow — every section must be present:

1. HOOK (1 sentence): A scroll-stopping opening that speaks directly to the audience's desire, aspiration, or pain point. Not a brand intro — an emotional trigger.

2. PRODUCT STORY (1–2 sentences): Name '{product_name}' specifically. State its single most compelling benefit and price if available. Make it feel desirable and worth having right now.

3. SERVICE STORY (1–2 sentences): Name '{service_name}' specifically. Describe the experience or transformation it delivers. Make it feel like something they'd regret missing.

4. COMBINED VALUE (1 sentence): Why having BOTH the {product_name} and the {service_name} from {company_name} is a complete solution — not two separate things but one powerful offering. This is the SmartPost core message.

5. CALL TO ACTION (1 sentence): Specific, direct, connected to the offering. Tell them exactly what to do next. Urgency or benefit signal where natural.

TONE: {effective_voice}. {f"Write like: {writing_style[:100]}" if writing_style else ""}
EMOJIS: Use strategically — one per key point, not decorative. Each emoji must earn its place.
SPECIFICITY RULE: Every sentence must earn its place. No filler, no vague positivity. If it could be written for any brand, rewrite it for {company_name} only.
{"VARIATION RULE: Version A = product-led hook, Version B = service-led hook, Version C = combined-value hook. Different opening energy, same complete story." if num_captions > 1 else ""}
''' if _has_multi_offering else f'''
1. Open with a scroll-stopping hook — the first line decides if people read on
2. 3–5 sentences clearly communicating the value proposition{f" of {product_name or service_name}" if (product_name or service_name) else ""}
3. Match the brand tone{f" — write like: {writing_style[:100]}..." if writing_style else ""}
4. Be specific — name the offering, key benefit, and price where relevant
5. Include emojis appropriately{f" — USE THESE: {festival_context.get('emoji', '')}" if festival_context else ""}
6. End with a compelling, actionable closing line
{"7. Each variation must take a DIFFERENT narrative angle" if num_captions > 1 else ""}
'''}
{f"FESTIVAL RULE: MUST include '{festival_context.get('greeting', '')}' and reference {festival_context.get('name', '')} specifically" if festival_context else ""}

RESPOND WITH VALID JSON ONLY (no markdown):
{{
    "captions": [
        {{
            "caption": "Your engaging caption with emojis...",
            "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3", ...]
        }}{"," if num_captions > 1 else ""}
        {"..." if num_captions > 1 else ""}
    ]
}}
"""

        try:
            response = await gemini_client.aio.models.generate_content(
                model=gemini_model,
                contents=prompt
            )

            # Bulletproof text extraction
            response_text = None
            if hasattr(response, 'text') and response.text:
                response_text = response.text.strip()
            elif hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, 'content') and candidate.content:
                    if hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'text') and part.text:
                                response_text = part.text.strip()
                                break

            if not response_text:
                logger.error("[ERROR] Gemini returned empty response for smart-post captions")
                if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                    logger.error(f"[BLOCKED] Prompt feedback: {response.prompt_feedback}")
                raise ValueError("Empty response from Gemini")

            usage = getattr(response, 'usage_metadata', None)
            if usage:
                logger.info(f"Caption Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

            # Clean markdown if present
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()

            # Extract JSON
            if not response_text.startswith("{"):
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1
                if start_idx != -1 and end_idx > start_idx:
                    response_text = response_text[start_idx:end_idx]

            result = json.loads(response_text)
            captions_data = result.get("captions", [])

            captions = []
            for idx, cap_data in enumerate(captions_data[:num_captions]):
                caption_text = cap_data.get("caption", "")
                hashtags = [f"#{tag.lstrip('#')}" for tag in cap_data.get("hashtags", [])]

                captions.append(SmartPostCaption(
                    caption=caption_text,
                    hashtags=hashtags[:10],
                    variation_label=variation_labels[idx] if idx < len(variation_labels) else None
                ))

            # Ensure we have the right number of captions
            while len(captions) < num_captions:
                captions.append(SmartPostCaption(
                    caption=f"Discover {company_name}! {company_description or 'Excellence in everything we do.'} 🌟",
                    hashtags=[f"#{company_name.lower().replace(' ', '')}", "#business", "#quality"],
                    variation_label=variation_labels[len(captions)] if len(captions) < len(variation_labels) else None
                ))

            return captions

        except Exception as e:
            logger.error(f"Caption generation error: {e}")
            fallback = SmartPostCaption(
                caption=f"Discover {company_name}! {company_description or 'Excellence in everything we do.'}!",
                hashtags=[f"#{company_name.lower().replace(' ', '').replace('-', '')}", "#business", "#quality", "#excellence"],
                variation_label=variation_labels[0] if variation_labels else None
            )
            return [fallback] * num_captions

    # ─────────────────────────────────────────────────────────────────────────
    # LAYER 2 — CAROUSEL PLANNER
    # One structured text call that produces the full carousel plan:
    # visual_contract (binding design rules) + per-slide briefs + caption.
    # ─────────────────────────────────────────────────────────────────────────

    def _build_fallback_plan(company_name, tagline, brand_colors, slide_roles, slide_count):
        """Minimal deterministic fallback if the planner API call fails."""
        slides = []
        for i, role in enumerate(slide_roles[:slide_count]):
            slides.append({
                "slide_number": i + 1,
                "role": role,
                "visual_concept": f"Professional marketing image for {company_name} — {role.lower().replace('_', ' ')} beat",
                "composition_note": "Central composition with brand colors dominant throughout",
                "typography_direction": f"Brand statement for {company_name} — clear, confident, {tagline or 'value-driven'}. Line 1: brand name or core promise — short and punchy. Line 2: key benefit or supporting statement — clear and complete.",
                "transition_note": "FINAL" if i == slide_count - 1 else "Continue the visual theme",
            })
        return {
            "visual_contract": {
                "composition_grid": "Central subject, text always in lower third",
                "color_temperature": "Match brand palette exactly",
                "typography_zone": "Lower third — consistent across all slides",
                "graphic_motif": "Brand color accent line above headline",
                "logo_position": "Bottom-right corner on every slide",
                "render_style": "photorealistic",
            },
            "slides": slides,
            "caption": f"Discover {company_name}. {tagline or 'Excellence in everything we do.'}",
            "hashtags": [f"#{company_name.lower().replace(' ', '')}", "#business", "#quality"],
        }

    async def _plan_carousel(
        company_name: str,
        company_description: str,
        tagline: str,
        brand_voice: str,
        brand_colors: str,
        posting_goal_str: str,
        goal_context: dict,
        creative_brief: str,
        platform_name: str,
        arc_key: str,
        arc_def: dict,
        slide_roles: list,
        slide_count: int,
        festival_context: Optional[dict] = None,
        tone_attributes_list: Optional[list] = None,
        writing_style: Optional[str] = None,
    ) -> dict:
        """
        Layer 2: Generate the complete carousel plan in one text API call.
        Returns visual_contract + per-slide briefs + caption + hashtags.
        """
        slide_role_lines = "\n".join([
            f"  Slide {i+1} [{role}]: {SLIDE_ROLE_DESCRIPTIONS.get(role, 'Execute with maximum creative impact.')}"
            for i, role in enumerate(slide_roles)
        ])

        festival_note = ""
        if festival_context:
            _fc_name = festival_context.get('name', '')
            _fc_greeting = festival_context.get('greeting', f'Happy {_fc_name}')
            _fc_colors = ', '.join(festival_context['colors']) if festival_context.get('colors') else f"culturally authentic colors for {_fc_name}"
            _fc_elements = ', '.join(festival_context['elements'][:4]) if festival_context.get('elements') else f"traditional visual elements for {_fc_name}"
            festival_note = f"""
FESTIVAL OVERRIDE (apply to ALL slides):
Festival: {_fc_name} | Greeting: "{_fc_greeting}"
Palette: {_fc_colors} | Elements: {_fc_elements}
ALL slides must use the festival's authentic visual language, colors, and cultural elements.
"""

        prompt = f"""You are a master creative director planning a {slide_count}-slide social media carousel for {platform_name}.

BRAND:
Company: {company_name}
Description: {(company_description or 'Professional brand')[:280]}
Tagline: "{tagline or '—'}"
Brand Voice: {brand_voice or 'Professional and trustworthy'}
Brand Colors: {brand_colors or 'Industry-appropriate palette'}
{f"Tone: {', '.join(tone_attributes_list)}" if tone_attributes_list else ""}
{f"Writing Style: {writing_style}" if writing_style else ""}

CAMPAIGN:
Goal: {posting_goal_str} — {goal_context.get('focus', '')}
Creative Direction: {creative_brief}
Arc Type: {arc_def['name']} — {arc_def['description']}
{festival_note}
SLIDE ROLES:
{slide_role_lines}

DELIVER a complete carousel plan as JSON. Requirements:

1. VISUAL CONTRACT — binding design rules ALL {slide_count} slides must strictly obey:
   - composition_grid: exact subject placement + text zone rule (e.g. "Subject always left-third, text right-half")
   - color_temperature: locked warm/cool/neutral and the specific palette feel
   - typography_zone: where text ALWAYS lives on every slide (e.g. "Bottom-left quarter, always")
   - graphic_motif: one repeating visual element on EVERY slide (e.g. "Thin gold rule above headline")
   - logo_position: fixed corner across all slides
   - render_style: "photorealistic" | "graphic_design" | "hybrid" — consistent throughout

2. PER-SLIDE BRIEFS — for each of the {slide_count} slides:
   - slide_number, role
   - visual_concept: specific scene/composition description (60–90 words) — exactly what to render
   - composition_note: how this slide's layout follows the visual contract and relates to adjacent slides
   - typography_direction: A creative brief for the text on this slide — describe the EMOTIONAL REGISTER,
     MESSAGE INTENT, and approximate WORD COUNT. Do NOT write the actual copy — describe what the copy
     must achieve and how it should feel. The image model will write the actual words.
     Example: "Provocative 3-4 word question that creates instant recognition of the pain. Supporting
     line (5-8 words) sharpens the specific struggle without resolving it — leave the viewer wanting slide 2."
   - transition_note: how this slide visually hands off to the next (write "FINAL" on the last slide)

3. CAPTION: one master social caption covering the full carousel arc (3–5 sentences, brand voice matched)
4. HASHTAGS: 8–10 relevant tags

Respond with VALID JSON only — no markdown fences:
{{
  "visual_contract": {{
    "composition_grid": "...",
    "color_temperature": "...",
    "typography_zone": "...",
    "graphic_motif": "...",
    "logo_position": "...",
    "render_style": "..."
  }},
  "slides": [
    {{
      "slide_number": 1,
      "role": "...",
      "visual_concept": "...",
      "composition_note": "...",
      "typography_direction": "Creative brief — emotional register + intent + word count. NOT actual copy.",
      "transition_note": "..."
    }}
  ],
  "caption": "...",
  "hashtags": ["#tag1", "#tag2"]
}}"""

        try:
            response = await gemini_client.aio.models.generate_content(
                model=gemini_model,
                contents=prompt,
            )
            response_text = None
            if hasattr(response, 'text') and response.text:
                response_text = response.text.strip()
            elif hasattr(response, 'candidates') and response.candidates:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text = part.text.strip()
                        break

            if not response_text:
                raise ValueError("Empty planner response")

            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            if not response_text.startswith("{"):
                s = response_text.find("{")
                e = response_text.rfind("}") + 1
                if s != -1:
                    response_text = response_text[s:e]

            usage = getattr(response, 'usage_metadata', None)
            if usage:
                logger.info(f"   [PLANNER] Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

            plan = json.loads(response_text)
            logger.info(f"   [PLANNER] Arc: {arc_def['name']} | {len(plan.get('slides', []))} slides planned")
            for s in plan.get('slides', []):
                logger.info(f"   [PLANNER] Slide {s.get('slide_number')} [{s.get('role')}]: brief=\"{s.get('typography_direction', '')[:80]}\"")
            return plan

        except Exception as e:
            logger.error(f"   [PLANNER] Failed ({e}) — using fallback plan")
            return _build_fallback_plan(company_name, tagline, brand_colors, slide_roles, slide_count)

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL IMPL — called by the endpoint in both normal and SSE modes.
    # All UploadFile bytes must be resolved BEFORE calling this function.
    # ─────────────────────────────────────────────────────────────────────────
    async def _smart_post_impl(
        company_name: str,
        company_description: Optional[str],
        website: Optional[str],
        logo_bytes: Optional[bytes],
        tagline: Optional[str],
        brand_voice: Optional[str],
        brand_colors: Optional[str],
        tone_attributes: Optional[str],
        writing_style: Optional[str],
        posting_goal: PostingGoal,
        content_mode: ContentGenerationMode,
        media_type: MediaType,
        custom_prompt: Optional[str],
        target_platform: Optional[str],
        reference_image_data: Optional[dict],
        queue: asyncio.Queue,
        # Product fields
        product_name: Optional[str] = None,
        product_description: Optional[str] = None,
        product_price: Optional[str] = None,
        product_category: Optional[str] = None,
        product_features: Optional[str] = None,
        product_benefits: Optional[str] = None,
        product_image_data: Optional[dict] = None,
        # Service fields
        service_name: Optional[str] = None,
        service_description: Optional[str] = None,
        service_price: Optional[str] = None,
        service_duration: Optional[str] = None,
        service_category: Optional[str] = None,
        service_features: Optional[str] = None,
        service_benefits: Optional[str] = None,
        service_image_data: Optional[dict] = None,
        # Variants (single image mode only)
        num_variants: int = 1,
    ) -> SmartPostResponse:
        """Core smart post generation logic — no UploadFile dependencies."""

        try:
            post_id = str(uuid.uuid4())
            logger.info(f"\n{'=' * 70}")
            logger.info(f"[SMART MODE] Starting post generation: {post_id[:8]}")
            logger.info(f"Company: {company_name}")
            logger.info(f"Goal: {posting_goal.value}")
            logger.info(f"Mode: {content_mode.value}")
            logger.info(f"Media: {media_type.value}")
            logger.info(f"{'=' * 70}")
            await queue.put({
                "step": "started",
                "message": f"Generating smart post for {company_name}",
            })

            # ═══════════════════════════════════════════════════════════════
            # PARSE BRAND VOICE PARAMETERS (comma-separated strings → lists)
            # ═══════════════════════════════════════════════════════════════
            tone_attributes_list = []
            if tone_attributes and tone_attributes.strip():
                tone_attributes_list = [t.strip() for t in tone_attributes.split(',') if t.strip()]
                logger.info(f"[BRAND] Tone attributes: {tone_attributes_list}")

            if writing_style:
                logger.info(f"[BRAND] Writing style: {writing_style[:50]}...")

            # Get goal context for prompts
            goal_context = _get_posting_goal_context(posting_goal)

            # ═══════════════════════════════════════════════════════════════
            # FESTIVAL CONTEXT (for Festival/Event posting goal)
            # Festival name/details come entirely from custom_prompt.
            # No hardcoded database — Gemini uses its own cultural knowledge
            # to generate authentic visuals for any festival worldwide.
            # A calendar API integration will be added in a future version.
            # ═══════════════════════════════════════════════════════════════
            festival_context = None
            detected_festival_name = None

            if posting_goal == PostingGoal.festival_event:
                logger.info(f"\n[FESTIVAL] Festival/Event goal detected")

                # Use custom_prompt as the festival name/description.
                # Users should mention the festival here (e.g. "Diwali", "Christmas").
                if custom_prompt and custom_prompt.strip():
                    detected_festival_name = custom_prompt.strip()
                    festival_context = {
                        "name": detected_festival_name,
                        "greeting": f"Happy {detected_festival_name}",
                        "themes": ["celebration", "joy", "festivity"],
                        "colors": [],    # Gemini uses its own cultural knowledge
                        "elements": [], # Gemini uses its own cultural knowledge
                        "emoji": "🎉✨🎊",
                        "formatted_date": "Upcoming"
                    }
                else:
                    # No festival specified — generic celebration
                    festival_context = {
                        "name": "Special Celebration",
                        "greeting": "Let's Celebrate",
                        "themes": ["celebration", "joy", "special occasion"],
                        "colors": [],
                        "elements": [],
                        "emoji": "🎉✨🎊",
                        "formatted_date": "Upcoming"
                    }

                logger.info(f"[FESTIVAL] Name: {festival_context.get('name', 'Unknown')}")
                logger.info(f"[FESTIVAL] Greeting: {festival_context.get('greeting', '')}")

            # ═══════════════════════════════════════════════════════════════
            # LAYER 1: ARC SELECTOR — Carousel only (zero API calls)
            # ═══════════════════════════════════════════════════════════════
            carousel_plan = None
            visual_contract = {}
            slides_plan = []
            arc_key = None
            arc_def = None
            slide_roles = []

            if media_type == MediaType.image_carousel:
                arc_key, arc_def, num_images = _select_carousel_arc(
                    posting_goal.value, brand_voice or '', company_description or '',
                    requested_count=num_variants,
                )
                slide_roles = _get_slide_roles(arc_key, num_images)
                logger.info(f"   [ARC] Selected: {arc_def['name']} | Slides: {num_images} | Roles: {slide_roles}")
            else:
                num_images = max(1, min(5, num_variants))  # variants: 1–5 for single image mode

            # Get platform specs
            platform = target_platform.lower() if target_platform else "instagram"
            if platform not in CAMPAIGN_PLATFORM_SPECS:
                platform = "instagram"
            platform_spec = CAMPAIGN_PLATFORM_SPECS[platform]

            # ═══════════════════════════════════════════════════════════════
            # STEP 1: CAPTIONS + DISPLAY TEXT
            # Carousel → Layer 2 Planner (1 structured text call)
            # Single/A-B → existing reversed-flow caption generation
            # ═══════════════════════════════════════════════════════════════
            if media_type == MediaType.image_carousel:
                logger.info(f"\n   [STEP 1] Running Carousel Planner — {arc_def['name']}...")
                await queue.put({"step": "planning", "message": f"Planning your {num_images}-slide carousel..."})
                _creative_brief = custom_prompt or f"Create a compelling {posting_goal.value.lower()} carousel for {company_name} that tells a story across {num_images} slides."
                carousel_plan = await _plan_carousel(
                    company_name=company_name,
                    company_description=company_description,
                    tagline=tagline,
                    brand_voice=brand_voice,
                    brand_colors=brand_colors,
                    posting_goal_str=posting_goal.value,
                    goal_context=goal_context,
                    creative_brief=_creative_brief,
                    platform_name=platform_spec['name'],
                    arc_key=arc_key,
                    arc_def=arc_def,
                    slide_roles=slide_roles,
                    slide_count=num_images,
                    festival_context=festival_context,
                    tone_attributes_list=tone_attributes_list,
                    writing_style=writing_style,
                )
                visual_contract = carousel_plan.get('visual_contract', {})
                slides_plan = carousel_plan.get('slides', [])
                num_images = len(slides_plan) or num_images  # Honour planner's actual count

                _plan_caption = carousel_plan.get('caption', f'Discover {company_name}')
                _plan_hashtags = [f"#{h.lstrip('#')}" for h in carousel_plan.get('hashtags', [])]
                captions = [SmartPostCaption(
                    caption=_plan_caption,
                    hashtags=_plan_hashtags[:10],
                    variation_label=None,
                )]
                logger.info(f"   [STEP 1] Planner complete — {len(slides_plan)} slides, visual contract ready")

            else:
                # Single post / A/B: existing reversed-flow caption generation
                logger.info(f"\n   [STEP 1] Generating captions + display text (reversed flow)...")
                await queue.put({"step": "captions", "message": "Generating captions..."})
                if festival_context:
                    logger.info(f"   [CAPTIONS] Festival context: {festival_context.get('name', 'Unknown')}")

                captions = await _generate_smart_captions(
                    company_name=company_name,
                    company_description=company_description,
                    tagline=tagline,
                    brand_voice=brand_voice,
                    posting_goal=posting_goal,
                    content_mode=content_mode,
                    goal_context=goal_context,
                    festival_context=festival_context,
                    tone_attributes_list=tone_attributes_list,
                    writing_style=writing_style,
                    custom_prompt=custom_prompt,
                    product_name=product_name,
                    product_description=product_description,
                    product_price=product_price,
                    product_features=product_features,
                    product_benefits=product_benefits,
                    service_name=service_name,
                    service_description=service_description,
                    service_price=service_price,
                    service_duration=service_duration,
                    service_features=service_features,
                    service_benefits=service_benefits,
                )
                logger.info(f"   [STEP 1] {len(captions)} caption(s) generated")


            # ═══════════════════════════════════════════════════════════════
            # GENERATE IMAGES
            # Carousel  → Layer 3: sequential with visual continuity reference
            # Single/AB → unchanged parallel path (1 image, no ordering needed)
            # ═══════════════════════════════════════════════════════════════

            # ── shared helper: build festival section for image prompts ──────
            def _build_festival_image_section(fc):
                if not fc:
                    return ""
                name = fc.get('name', 'Festival')
                greeting = fc.get('greeting', f'Happy {name}')
                colors_line = ', '.join(fc['colors']) if fc.get('colors') else f"culturally authentic colors for {name}"
                elements_line = '\n'.join(['• ' + e for e in fc['elements'][:5]]) if fc.get('elements') else f"• Traditional visual elements authentic to {name}"
                return f"""
⚠️⚠️⚠️ FESTIVAL/EVENT POST (MUST FOLLOW EXACTLY) ⚠️⚠️⚠️
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎉 FESTIVAL: {name}
🎊 GREETING TEXT TO DISPLAY PROMINENTLY: "{greeting}"
VISUAL ELEMENTS — use your cultural knowledge for {name}:
{elements_line}
COLORS — use culturally authentic palette: {colors_line}
⛔ Image MUST be specifically for {name}. DO NOT mix elements from other festivals.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

            # ── LAYER 3: sequential carousel slide generator ─────────────────
            async def _generate_carousel_slide(slide_data: dict, vc: dict, prev_slide_bytes: Optional[bytes]):
                """
                Generate one carousel slide.
                prev_slide_bytes → fed as visual continuity reference so Gemini
                can see what the previous slide looked like and match it.
                Returns (SmartPostImage, raw_image_bytes) or (None, None).
                """
                img_num   = slide_data['slide_number']
                role      = slide_data.get('role', '')
                v_concept = slide_data.get('visual_concept', '')
                comp_note = slide_data.get('composition_note', '')
                trans     = slide_data.get('transition_note', '')
                typography_direction = slide_data.get('typography_direction', f"Brand-appropriate text for this {role} slide — bold primary line + supporting line.")

                logger.info(f"\n   [SLIDE {img_num}/{num_images}] Role: {role}")

                effective_voice  = brand_voice or 'Professional yet approachable'
                effective_colors = brand_colors or 'Modern, appealing brand colors'
                _font_style      = _get_smartpost_font_style(effective_voice)
                _logo_instr      = (
                    "Integrate the brand logo (provided in this request) as a natural design element — designed in, not pasted on. Surroundings harmonize with logo colors. PIXEL-PERFECT: do NOT alter logo colors, fonts, shapes, or styling — resize only."
                    if logo_bytes else "No logo — do not invent any brand mark."
                )

                # Visual contract block (binds all slides)
                vc_block = f"""VISUAL CONTRACT — ALL {num_images} SLIDES SHARE THESE RULES (ENFORCE STRICTLY):
Composition Grid : {vc.get('composition_grid', 'Subject-led, text always in defined zone')}
Color Temperature: {vc.get('color_temperature', 'Match brand palette')}
Typography Zone  : {vc.get('typography_zone', 'Consistent zone across all slides')}
Graphic Motif    : {vc.get('graphic_motif', 'Brand accent element on every slide')}
Logo Position    : {vc.get('logo_position', 'Fixed corner, every slide')}
Render Style     : {vc.get('render_style', 'photorealistic')}"""

                is_final = (trans == "FINAL" or img_num == num_images)
                slide_block = f"""{SPELLING_PRIORITY_PREAMBLE}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SLIDE {img_num} OF {num_images} — ROLE: {role}
{SLIDE_ROLE_DESCRIPTIONS.get(role, 'Execute with maximum creative impact.')}

VISUAL CONCEPT FOR THIS SLIDE:
{v_concept}

COMPOSITION NOTE:
{comp_note}
{f'''
▸ REFERENCE SUBJECT — VISUAL HERO OF THIS SLIDE:
Creative direction: {custom_prompt or 'Feature the provided subject prominently as the visual hero of this slide.'}
The reference subject is the centrepiece of this slide.
Place them as the dominant compositional element — FULLY within frame with breathing space on all sides. Never crop any edge at the canvas boundary.
Maintain exact facial likeness for people. Maintain exact form and color for products.
''' if reference_image_data and reference_image_data.get("success") else ""}
▸ TYPOGRAPHY — designed into this slide, not placed on top:
COPY MANDATE for this {role} slide — write original copy specific to this slide's narrative purpose:
  Planner's direction: {typography_direction}
  Line 1 (bold, large — 4 to 7 words): The primary hook for a {role} slide — specific to {company_name}, impossible to ignore. Not the same line as any other slide in this series.
  Line 2 (medium weight, smaller — maximum 12 words): The supporting line that advances the {role} narrative — concrete benefit, tension, or direct follow-through. Semantically complete on its own.

ONE ZONE — ALL TEXT IN A SINGLE PLANNED BLOCK:
Both lines sit together in one pre-planned typographic zone. Plan the zone before any visual element is placed.
✗ Do NOT place the headline top and the subline at the bottom — this is the most common failure mode
✗ Do NOT echo or repeat any text element elsewhere in the frame
✗ Do NOT render the labels "Line 1", "Line 2", "Headline", or "Subline" — render the actual copy only

Font: {_font_style}
Text color drawn from this slide's palette — harmonize with {effective_colors}. Directional shadow matching this slide's light source.
{TYPOGRAPHY_PRECISION}

{"TRANSITION → " + trans if not is_final else "FINAL SLIDE — Make this the most memorable. Leave a lasting impression."}"""

                image_prompt = f"""You are an elite art director generating slide {img_num} of a {num_images}-slide carousel — one unified campaign, not {num_images} separate images.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PAYLOAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company: {company_name}
Tagline: "{tagline or '—'}"
Brand Voice: {effective_voice}
Brand Colors: {effective_colors}
Profile: {(company_description or 'Professional brand')[:250]}
{f"Tone: {', '.join(tone_attributes_list)}" if tone_attributes_list else ""}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{vc_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{slide_block}
{_build_festival_image_section(festival_context)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LOGO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_logo_instr}

{REALISM_STANDARD}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ABSOLUTE PROHIBITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{NEGATIVE_PROMPT}
✗ No adult/sexual/violent content  ✗ No emojis or emoji-style graphics
✗ No generic stock-photo feel  ✗ No AI-generated look
✗ No anatomical misalignment — face MUST match body orientation. No twisted necks. No ghost anatomy.
{"✓ Logo: integrate naturally, surroundings harmonize with logo colors" if logo_bytes else "✗ Do NOT invent any logo or brand mark"}
"""
                try:
                    contents = [image_prompt]

                    # Logo injection FIRST — must be the first image Gemini sees so it anchors as the locked identity asset
                    if logo_bytes:
                        _lm = "image/jpeg" if logo_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                        contents.append({"inline_data": {"mime_type": _lm, "data": base64.b64encode(logo_bytes).decode("utf-8")}})
                        contents.append("LOGO REFERENCE: This is the exact brand logo — treat it as a LOCKED, PIXEL-PERFECT asset. ABSOLUTELY DO NOT change any logo colors, fonts, shapes, icons, or styling. Every color must appear exactly as shown here. The only allowed operation is resizing/scaling. No recoloring, no reinterpreting, no redesigning — ever.")

                    # Previous slide → visual continuity reference (comes AFTER logo so logo identity wins over style continuity)
                    if prev_slide_bytes is not None:
                        _pm = "image/jpeg" if prev_slide_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                        contents.append({"inline_data": {"mime_type": _pm, "data": base64.b64encode(prev_slide_bytes).decode("utf-8")}})
                        contents.append(f"VISUAL CONTINUITY REFERENCE: This is slide {img_num - 1} — use it for layout rhythm, color temperature, and visual grammar only. Do NOT copy the logo appearance from this slide — always use the locked logo provided above. Do not copy the layout — evolve it. The series must feel like one unified campaign.")

                    # Reference subject — injected on every carousel slide so the subject appears consistently
                    if reference_image_data and reference_image_data.get("success"):
                        _ref_mime = reference_image_data.get("mime_type", "image/jpeg")
                        _ref_b64  = reference_image_data.get("base64_data", "")
                        _subject_label = custom_prompt or "the subject"
                        contents.append({"inline_data": {"mime_type": _ref_mime, "data": _ref_b64}})
                        contents.append(
                            f"REFERENCE SUBJECT IMAGE — {_subject_label} must be the VISUAL HERO of this slide. "
                            f"For people: faithfully reproduce their facial features, skin tone, hairstyle, and overall likeness — do NOT alter their appearance. "
                            f"For products/objects: reproduce exact form, color, and design. "
                            f"Feature them prominently — composition, colors, and brand elements must frame and celebrate this subject."
                        )
                        logger.info(f"   [SLIDE {img_num}] Reference subject injected: {_subject_label}")

                    from google.genai import types as _types
                    response = await gemini_client.aio.models.generate_content(
                        model=image_model,
                        contents=contents,
                        config=_types.GenerateContentConfig(
                            temperature=0.75,
                            response_modalities=["IMAGE"],
                            image_config=_types.ImageConfig(aspect_ratio=platform_spec['gemini_aspect'])
                        )
                    )
                    usage = getattr(response, 'usage_metadata', None)
                    if usage:
                        logger.info(f"   [SLIDE {img_num}] Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

                    raw_bytes = None
                    if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                raw_bytes = part.inline_data.data
                                break

                    if not raw_bytes:
                        logger.error(f"   [SLIDE {img_num}] No image data in response")
                        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                            logger.error(f"   [SLIDE {img_num}] Feedback: {response.prompt_feedback}")
                        return None, None

                    save_result = _save_smart_post_image(
                        image_bytes=raw_bytes, post_id=post_id,
                        company_name=company_name, slide_number=img_num
                    )
                    logger.info(f"   [SLIDE {img_num}] ✓ Saved: {save_result['url']}")
                    return SmartPostImage(
                        image_url=save_result["url"],
                        image_preview=f"data:image/png;base64,{base64.b64encode(raw_bytes).decode('utf-8')}",
                        local_path=save_result["local_path"],
                        slide_number=img_num,
                    ), raw_bytes

                except Exception as e:
                    logger.error(f"   [SLIDE {img_num}] Failed: {e}")
                    logger.error(traceback.format_exc())
                    return None, None

            # ── LLM-generated creative briefs — fresh, brand-tailored, every run ─
            async def _generate_variant_briefs(n: int) -> list:
                """
                One fast text call → N unique creative directions tailored to THIS brand.
                Returns list of dicts: territory, visual_concept, composition, light_color, emotional_payoff.
                Never repeats — temperature 0.85 guarantees fresh output every run.
                """
                _eff_voice   = brand_voice or 'Professional yet approachable'
                _eff_colors  = brand_colors or 'Modern, on-brand colors'
                _eff_tagline = tagline or ''
                _eff_desc    = (company_description or '')[:300]

                _item_ctx = ""
                if product_name:
                    _item_ctx += f"\nProduct: {product_name}"
                    if product_description: _item_ctx += f" — {product_description[:120]}"
                    if product_price:       _item_ctx += f" | {product_price}"
                if service_name:
                    _item_ctx += f"\nService: {service_name}"
                    if service_description: _item_ctx += f" — {service_description[:120]}"

                # Detect composite mode for brief generation
                _bi_has_product = bool(product_image_data and product_image_data.get("success"))
                _bi_has_service = bool(service_image_data and service_image_data.get("success"))
                _bi_has_ref     = bool(reference_image_data and reference_image_data.get("success"))
                _bi_asset_count = sum([_bi_has_product, _bi_has_service, _bi_has_ref])
                _bi_is_composite = _bi_asset_count >= 2

                if _bi_is_composite:
                    _asset_list = []
                    if _bi_has_product: _asset_list.append(f"Product image: {product_name or 'product'} (tangible anchor — sharp foreground)")
                    if _bi_has_service: _asset_list.append(f"Service image: {service_name or 'service'} (experiential layer — context or atmosphere)")
                    if _bi_has_ref:     _asset_list.append("Reference subject: person or scene (emotional core)")
                    _composite_brief_note = f"""
COMPOSITE IMAGE MODE — {_bi_asset_count} VISUAL ASSETS WILL BE PROVIDED:
{chr(10).join('  • ' + a for a in _asset_list)}

Every creative direction you generate MUST be designed for a COMPOSITE layout — not a single subject.
Each direction must describe how ALL {_bi_asset_count} assets are arranged together as one unified marketing image.
The visual_concept must explicitly name each asset's position and role in the frame.
The composition must describe a multi-zone layout — one zone per asset plus a typography zone.
Think like a multi-product advertising layout director, not a single-hero photographer.
"""
                else:
                    _composite_brief_note = ""

                _diversity_note = (
                    f"\n\nCRITICAL — MAXIMUM VARIETY: Each of the {n} directions must be visually "
                    f"INCOMPATIBLE with the others. Different scene, different compositional axis, "
                    f"different emotional register. Think {n} different world-class creative directors "
                    f"each pitching their own independent interpretation of the same brief."
                    if n > 1 else ""
                )

                _brief_prompt = f"""You are a Senior Creative Director at a world-class agency (Wieden+Kennedy, BBDO, Droga5 calibre).

Task: Generate {n} creative direction(s) for a social media marketing image.

BRAND BRIEF:
Company: {company_name}
Brand Voice: {_eff_voice}
Brand Colors: {_eff_colors}
Tagline: {_eff_tagline or '—'}
Profile: {_eff_desc}
Goal: {posting_goal.value}
Platform: {platform_spec['name']}{f" | Custom Direction: {custom_prompt}" if custom_prompt else ""}
{_item_ctx}
{_composite_brief_note}
WHAT THE PIPELINE ALREADY HANDLES — do NOT repeat in your output:
Brand color application, logo placement, typography layout rules, platform dimensions, safety filters.

YOUR EXCLUSIVE JOB — supply ONLY what the pipeline cannot derive:
• VISUAL CONCEPT — exactly what is IN this image and where each element sits
• COMPOSITION & FRAMING — camera angle, focal point, spatial zones for each asset
• LIGHT & COLOR — quality of light, palette mood, unified atmosphere across all elements
• EMOTIONAL PAYOFF — the precise feeling the viewer gets in 0.3 seconds{_diversity_note}

QUALITY BAR:
✓ "Product in sharp foreground lower-right, service environment blurred warmly behind, reference subject mid-left" — not "good layout"
✓ "Golden-hour rim light unified across all elements — same temperature ties the composite together" — not "nice lighting"
✓ Territory name must reflect the COMPLETE brand story, not a single element

Return ONLY a valid JSON array. No markdown fences, no explanation text. Exactly {n} object(s):
[
  {{
    "territory": "3–5 word creative territory — brand-specific, reflects the complete story",
    "visual_concept": "2–3 sentences: Exactly what is in this image — name EVERY asset and where it appears. Scene, arrangement, world.",
    "composition": "1–2 sentences: Spatial zones for each element — product zone, service zone, subject zone, text zone. Camera angle and depth.",
    "light_color": "1–2 sentences: Unified light quality and palette mood that ties all elements together as one image.",
    "emotional_payoff": "1 sentence: The precise feeling the viewer gets from the COMPLETE image in 0.3 seconds."
  }}
]"""

                try:
                    from google.genai import types as _gt
                    _resp = await gemini_client.aio.models.generate_content(
                        model=gemini_model,
                        contents=_brief_prompt,
                        config=_gt.GenerateContentConfig(temperature=0.85),
                    )
                    _text = None
                    if hasattr(_resp, 'text') and _resp.text:
                        _text = _resp.text.strip()
                    elif hasattr(_resp, 'candidates') and _resp.candidates:
                        for _p in _resp.candidates[0].content.parts:
                            if hasattr(_p, 'text') and _p.text:
                                _text = _p.text.strip()
                                break
                    if not _text:
                        raise ValueError("Empty brief response")
                    if "```json" in _text:
                        _text = _text.split("```json")[1].split("```")[0].strip()
                    elif "```" in _text:
                        _text = _text.split("```")[1].split("```")[0].strip()
                    _briefs = json.loads(_text)
                    if isinstance(_briefs, list) and len(_briefs) >= n:
                        logger.info(f"[BRIEFS] ✓ {len(_briefs)} creative direction(s) generated for {company_name}")
                        return _briefs[:n]
                    raise ValueError(f"Expected {n} briefs, got {len(_briefs) if isinstance(_briefs, list) else type(_briefs)}")
                except Exception as _e:
                    logger.warning(f"[BRIEFS] Generation failed ({_e}) — using structured fallback")
                    _fallback = [
                        {"territory": "Iconic Product Moment",      "visual_concept": f"The {product_name or company_name} offering elevated to an iconic object — aspirational lighting, clean isolation, desire-architecture composition.", "composition": "Center-frame with architectural negative space, eye-level camera, subject 100% within frame", "light_color": "Studio directional key light, brand colors in background gradient, high contrast", "emotional_payoff": "Instant desire — the viewer wants this in the first frame"},
                        {"territory": "Human Transformation Truth", "visual_concept": f"An unguarded human moment — a real person experiencing the positive change that {company_name} delivers. The emotion is the headline.", "composition": "Subject at one-third, natural context, candid mid-action angle, shallow depth of field", "light_color": "Warm natural window light, golden tones, authentic unmanipulated palette", "emotional_payoff": "Recognition — 'that could be me, that feeling could be mine'"},
                        {"territory": "Brand World Immersion",      "visual_concept": f"The aspirational lifestyle world {company_name} enables — a rich environmental scene where the brand belongs organically as part of life.", "composition": "Environmental wide with subject at one-third, deep background storytelling, foreground texture frame", "light_color": "Cinematic depth, brand colors woven into environment, atmospheric haze or glow", "emotional_payoff": "Aspiration — the viewer wants to live inside this world"},
                        {"territory": "Graphic Design Authority",   "visual_concept": f"{company_name}'s brand personality as pure visual energy — typography as the hero, geometry as the language, color as the voice.", "composition": "Bold geometric structure, flat or near-flat design, typography anchors the visual hierarchy", "light_color": "High contrast, brand colors at full saturation, graphic not photographic treatment", "emotional_payoff": "Impact — a scroll-stopper built from brand confidence alone"},
                        {"territory": "Craft and Material Truth",   "visual_concept": f"Extreme close-up on the single most compelling detail — texture, material, precision, or the exact moment of use. Specificity is desire.", "composition": "Macro tight crop, shallow depth of field, abstract edges bleeding at frame boundary", "light_color": "Raking side light to reveal surface texture, rich shadow depth, intimate intimate scale", "emotional_payoff": "Curiosity turning to desire — the detail tells the entire brand story"},
                    ]
                    return _fallback[:n]

            # ── Build product/service context for image prompt ────────────────
            def _build_item_section() -> str:
                """Build product/service context block injected into every image prompt."""
                parts = []
                if product_name:
                    feat = ", ".join([f.strip() for f in product_features.split("|") if f.strip()]) if product_features else ""
                    ben  = ", ".join([b.strip() for b in product_benefits.split("|") if b.strip()]) if product_benefits else ""
                    block = [f"Product: {product_name}"]
                    if product_description: block.append(f"What it is: {product_description[:250]}")
                    if product_price:       block.append(f"Price: {product_price}")
                    if product_category:    block.append(f"Category: {product_category}")
                    if feat:                block.append(f"Key Features: {feat}")
                    if ben:                 block.append(f"Key Benefits: {ben}")
                    parts.append(("PRODUCT TO FEATURE", "\n".join(block)))

                if service_name:
                    feat = ", ".join([f.strip() for f in service_features.split("|") if f.strip()]) if service_features else ""
                    ben  = ", ".join([b.strip() for b in service_benefits.split("|") if b.strip()]) if service_benefits else ""
                    block = [f"Service: {service_name}"]
                    if service_description: block.append(f"What it is: {service_description[:250]}")
                    if service_price:       block.append(f"Price: {service_price}")
                    if service_duration:    block.append(f"Duration: {service_duration}")
                    if service_category:    block.append(f"Category: {service_category}")
                    if feat:                block.append(f"Key Features: {feat}")
                    if ben:                 block.append(f"Key Benefits: {ben}")
                    parts.append(("SERVICE TO FEATURE", "\n".join(block)))

                if not parts:
                    return ""

                sep = "━" * 51
                out = f"\n{sep}\n"
                if len(parts) == 1:
                    label, body = parts[0]
                    out += f"{label}\n{sep}\n{body}\n"
                else:
                    # Both product AND service provided
                    out += f"PRODUCT & SERVICE TO FEATURE\n{sep}\n"
                    for label, body in parts:
                        out += f"── {label} ──\n{body}\n\n"
                    out += "Feature BOTH in the image — design a composition where product and service are clearly visible and visually complementary.\n"
                return out

            _item_section = _build_item_section()

            # ── Generate fresh creative briefs (one text call, brand-tailored) ─
            # When custom_prompt is set, the scene is already defined — skip the
            # brief-generation call entirely to avoid competing creative directions.
            if custom_prompt:
                _variant_briefs = [{"territory": f"Execution {i+1}", "visual_concept": "", "composition": "", "light_color": "", "emotional_payoff": ""} for i in range(num_images)]
            else:
                if num_images > 1:
                    await queue.put({"step": "planning", "message": f"Crafting {num_images} creative directions..."})
                _variant_briefs = await _generate_variant_briefs(num_images)

            # ── single-post image generator ───────────────────────────────────
            async def _generate_single_smart_image(img_num):
                """Generate a single smart-post image (single image / variant mode)."""
                logger.info(f"\n   [IMAGE {img_num}/{num_images}] Generating...")

                # Build festival-specific section for image prompt
                festival_image_section = _build_festival_image_section(festival_context)

                # Use direct parameters (with sensible defaults)
                effective_description = company_description or 'A professional business delivering excellence'
                effective_tagline = tagline
                effective_voice = brand_voice or 'Professional yet approachable'
                effective_colors = brand_colors or 'Modern, appealing colors that match the brand'

                _logo_instruction = (
                    "Integrate the brand logo (shown above) as a natural design element — place it in a compositionally clean zone where it feels purposefully designed in, not pasted on. The surrounding area must harmonize with the logo's own colors and style. PIXEL-PERFECT LOGO REPRODUCTION: The logo is a locked identity asset — do NOT recolor, restyle, reinterpret, redesign, or alter ANY element (colors, fonts, shapes, icons, arrangement). Every color in the logo must appear exactly as provided. Only resize/scale the logo as needed for placement — absolutely no other changes."
                    if logo_bytes else "No logo provided — do not invent or hallucinate any brand mark."
                )
                _creative_brief = custom_prompt if custom_prompt else f"Create a compelling {posting_goal.value.lower()} post for {company_name} that reflects the brand identity and stops the scroll on {platform_spec['name']}."
                _font_style = _get_smartpost_font_style(effective_voice)

                # ── Asset detection (used for composite mode logic below) ──
                _has_ref     = bool(reference_image_data and reference_image_data.get("success"))
                _has_product = bool(product_image_data and product_image_data.get("success"))
                _has_service = bool(service_image_data and service_image_data.get("success"))
                _asset_count = sum([_has_ref, _has_product, _has_service])

                # Composite mode overrides the single-subject visual approach
                if _asset_count >= 2:
                    _asset_labels = []
                    if _has_product: _asset_labels.append(product_name or "product")
                    if _has_service: _asset_labels.append(service_name or "service")
                    if _has_ref:     _asset_labels.append("reference subject")
                    _visual_approach = (
                        f"SELECTED APPROACH → COMPLETE BRAND STORY\n"
                        f"You are designing a single SmartPost image that tells the COMPLETE story of {company_name} in one frame. "
                        f"All provided assets — {', '.join(_asset_labels)} — must be visible and purposefully arranged. "
                        f"This is not a single-hero image. This is a designed composite where each element has a defined role: "
                        f"the product is the tangible offer (sharp, prominent), the service is the experiential context (atmospheric, supporting), "
                        f"and the reference subject is the emotional connection (human, relatable). "
                        f"The viewer must understand in 3 seconds: what {company_name} sells, what experience they provide, and why both matter. "
                        f"Design around the brand brief's creative direction while ensuring every asset earns its place in the final frame."
                    )
                else:
                    _visual_approach = _get_smartpost_visual_approach(posting_goal.value, effective_voice)
                _color_ref = effective_colors

                # Defaults — overridden in the else branch when variant briefs are used
                _b_territory = posting_goal.value.replace("_", " ").title()
                _b_payoff    = f"Experience the difference with {company_name}"
                _b_concept   = ""
                _b_comp      = ""
                _b_light     = ""

                # Creative direction — brief-based or custom_prompt anchored
                if custom_prompt:
                    # custom_prompt defines the scene; just vary composition across executions
                    if num_images > 1:
                        _variant_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EXECUTION {img_num} OF {num_images}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Apply the PRIMARY CREATIVE BRIEF above with a fresh perspective. Same scene and creative territory; a different compositional moment. This execution must be visually distinct from the others — vary the framing, camera angle, depth, or light quality while staying true to the brief.
"""
                    else:
                        _variant_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CREATIVE DIRECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Execute the PRIMARY CREATIVE BRIEF above faithfully. Translate the described scene into a high-impact marketing visual.
"""
                else:
                    _brief      = _variant_briefs[img_num - 1]
                    _b_territory = _brief.get("territory", f"Creative Direction {img_num}")
                    _b_concept   = _brief.get("visual_concept", "")
                    _b_comp      = _brief.get("composition", "")
                    _b_light     = _brief.get("light_color", "")
                    _b_payoff    = _brief.get("emotional_payoff", "")

                    if num_images > 1:
                        _v_label = f"VARIANT {img_num} OF {num_images} — {_b_territory}"
                        _v_footer = "\nThis variant must be visually INCOMPATIBLE with the others — different scene, different angle, different emotional world. Same brand payload; a completely different creative universe.\n"
                    else:
                        _v_label = f"CREATIVE DIRECTION — {_b_territory}"
                        _v_footer = ""

                    _variant_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_v_label}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISUAL CONCEPT: {_b_concept}
COMPOSITION: {_b_comp}
LIGHT & COLOR: {_b_light}
EMOTIONAL PAYOFF: {_b_payoff}{_v_footer}"""

                # ── Composite mandate — activate when 2+ asset images provided ──
                if _asset_count >= 2:
                    _asset_roles = []
                    if _has_product:
                        _asset_roles.append(f"  • PRODUCT ({product_name or 'product'}) — the tangible, purchasable anchor. Sharp focus, fully within frame, packaging and color pixel-accurate.")
                    if _has_service:
                        _asset_roles.append(f"  • SERVICE ({service_name or 'service'}) — the experiential layer. Can be atmospheric background, a defined zone, or blended into the scene — but clearly visible and recognisable.")
                    if _has_ref:
                        _asset_roles.append(f"  • REFERENCE SUBJECT — the human or hero element. The emotional core of the composition. Faithfully reproduced.")
                    _composite_mandate = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPOSITE IMAGE — {_asset_count} ASSETS PROVIDED (ALL MUST APPEAR)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_asset_count} visual assets have been provided. This image MUST be a thoughtfully designed composite where every asset is visible and tells a complete, unified brand story. This is NOT optional — if any provided asset is absent from the final image, it is a critical failure.

ASSET ROLES — assign each a spatial zone before generating:
{chr(10).join(_asset_roles)}

COMPOSITE DESIGN PRINCIPLES:
— Use depth, scale, and focus to establish hierarchy — not all assets at the same prominence
— Consistent light temperature, color palette, and brand tone unify all elements across the frame
— The product and service must feel narratively connected — the viewer immediately understands they belong to the same brand and offer
— The entire composition reads as ONE designed marketing image, not multiple photos stitched together
— Typography occupies its own pre-planned zone — separate from every asset zone
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
                else:
                    _composite_mandate = ""

                image_prompt = f"""{SPELLING_PRIORITY_PREAMBLE}
You are a world-class creative director, art director, and visual designer with 25+ years building award-winning campaigns for global brands across every industry — luxury, technology, healthcare, finance, consumer, enterprise.

Read the complete brand payload and creative brief. Then plan and generate a fully crafted marketing image — visual concept, composition, integrated typography, and logo placement — executed at agency level.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BRAND PAYLOAD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company: {company_name}
Tagline: "{effective_tagline or '—'}"
Brand Voice: {effective_voice}
Brand Colors: {effective_colors} ⛔ USE these colors as scene atmosphere and design tone — do NOT render color swatches, hex codes, or color palette boxes anywhere in the image.
Profile: {effective_description[:350]}
{f"Tone: {', '.join(tone_attributes_list)}" if tone_attributes_list else ""}
{f"Writing Style: {writing_style}" if writing_style else ""}
{_item_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CREATIVE BRIEF — Your design direction
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_creative_brief}

Goal: {posting_goal.value.upper()} — {goal_context['focus']}
Emotional Tone: {goal_context['tone']}
Visual Elements: {goal_context['visual']}
Platform: {platform_spec['name']} ({platform_spec['aspect_ratio']}) — {platform_spec['tone']}
{_variant_section}{festival_image_section}
{f'''━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REFERENCE SUBJECT — VISUAL HERO OF THIS POST
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A reference image is provided. Creative direction: {custom_prompt or 'feature the subject prominently as the visual hero'}
This is the VISUAL HERO and central subject of the post — not decoration, not background.
FEATURING RULES:
• Place this subject as the dominant compositional element
• Show the ENTIRE subject within frame — never crop any edge at the canvas boundary. The product or person must be 100% visible with intentional breathing space around it
• For people: preserve exact facial likeness, skin tone, hairstyle, and overall appearance faithfully
• For products/objects: preserve exact form, color, texture, and design — pixel accuracy matters
• Dress and present the subject appropriately for the theme and creative brief
• All other elements (background, colors, typography, brand) must FRAME and CELEBRATE this subject — they serve the subject, not compete with it
''' if _has_ref and _asset_count == 1 else f'''━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
REFERENCE SUBJECT — EMOTIONAL CORE OF THE COMPOSITE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A reference subject image is provided. In this composite, it plays the HUMAN/EMOTIONAL role — the person, scene, or context that creates connection with the audience.
• Faithfully reproduce the subject — exact likeness for people, exact form for objects
• Show the ENTIRE subject — no cropping at any canvas edge, intentional breathing space
• Position it as one equal component within the composite layout (alongside the product and service)
• It is NOT the sole hero — it shares equal compositional importance with the other provided assets
''' if _has_ref and _asset_count >= 2 else ""}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
YOUR DESIGN DECISIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
▸ STEP 1 — VISUAL APPROACH
{_visual_approach}

▸ STEP 2 — COMPOSITION & ATMOSPHERE
{_composite_mandate}Plan the focal point and spatial zones. The {_color_ref} is the emotional backbone of this image — dominant scene colors, lighting, materials, surfaces, and reflections MUST embody these brand colors. They must feel like they live IN the scene, not applied over it. Camera angle and depth of field reflect the brand's market tier and the creative brief's emotional direction.
SPATIAL RULES — establish these before placing any element:
— Every provided asset must be FULLY visible within frame — no cropping at canvas edges, intentional breathing space on all sides
— Text zone: plan a dedicated text zone before arranging any visual element — it occupies a zone no asset occupies. The text zone is designed in from the start, not found in leftover space afterward.

▸ STEP 3 — TYPOGRAPHY (DESIGNED INTO THE IMAGE, NOT PLACED ON TOP)
Design the typography as a native compositional element — font, color, placement, shadow, and weight conceived alongside the visual from the first stroke. The text must belong to this specific image.

COPY MANDATE — write original marketing copy for THIS image:
  Line 1 (bold, large — 4 to 7 words): Capture the creative territory "{_b_territory}" in one commanding, brand-specific headline. This is the line the audience reads in 0.3 seconds and cannot forget. No generic phrases — make it specific to {company_name}.
  Line 2 (medium weight, smaller — maximum 12 words): One concrete sentence that delivers: "{_b_payoff}". Aspirational or actionable. Never vague. The line that makes them want to act.

ONE ZONE — ALL TEXT IN A SINGLE PLANNED BLOCK:
Plan the text zone before placing any visual element. Commit to it. Both lines sit together in that one zone as a unified typographic block.
✗ Do NOT place the headline at the top and the subline at the bottom — this is the most common failure mode
✗ Do NOT repeat, echo, or shadow any text element anywhere else in the frame
✗ Do NOT render the labels "Line 1", "Line 2", "Headline", or "Subline" — render the actual copy only

Font: {_font_style}
Text color drawn from this image's own palette — harmonize with {_color_ref}. Apply a directional shadow matching the scene's light source.
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

                try:
                    # Build content for Gemini
                    contents = [image_prompt]

                    # Logo injection — send actual logo for Gemini to place in image
                    if logo_bytes:
                        _logo_mime = "image/jpeg" if logo_bytes[:3] == b'\xff\xd8\xff' else "image/png"
                        contents.append({"inline_data": {"mime_type": _logo_mime, "data": base64.b64encode(logo_bytes).decode("utf-8")}})
                        contents.append("LOGO REFERENCE: This is the exact brand logo — treat it as a LOCKED, PIXEL-PERFECT asset. Integrate it into the composition so it feels designed in, not pasted on. ABSOLUTELY DO NOT change any logo colors, fonts, shapes, icons, or styling. Do not reinterpret or redesign any part of it. The only allowed operation is resizing/scaling. Every color in this logo must appear exactly as shown.")

                    # Reference subject injection — becomes the visual hero of the post
                    if reference_image_data and reference_image_data.get("success"):
                        _ref_mime = reference_image_data.get("mime_type", "image/jpeg")
                        _ref_b64  = reference_image_data.get("base64_data", "")
                        _subject_label = custom_prompt or "the subject"
                        contents.append({"inline_data": {"mime_type": _ref_mime, "data": _ref_b64}})
                        if _asset_count >= 2:
                            contents.append(
                                f"REFERENCE SUBJECT — EMOTIONAL CORE OF THE COMPOSITE: This is {_subject_label}. "
                                f"Faithfully reproduce this subject in the final image — exact likeness for people (facial features, skin tone, hairstyle unchanged), exact form and color for objects. "
                                f"This subject is ONE equal component of the composite alongside the product and service — NOT the sole hero. "
                                f"Assign it a clear spatial zone within the composite layout. It must be fully within frame with breathing space on all sides."
                            )
                        else:
                            contents.append(
                                f"REFERENCE SUBJECT IMAGE — This is the actual photo of {_subject_label}. "
                                f"This person/subject MUST be the VISUAL HERO of the generated image — featured prominently at the centre of the composition. "
                                f"For people: faithfully reproduce their facial features, skin tone, hairstyle, and overall likeness. Do NOT alter their appearance, age, or identity. "
                                f"For products/objects: reproduce exact form, color, and design with precision. "
                                f"Frame them with brand colors, background, and typography that celebrate and elevate them. "
                                f"This is NOT a style reference — the actual person/subject shown MUST appear in the final generated image."
                            )
                        logger.info(f"[REF_IMAGE] ✓ Reference subject injected: {_subject_label}")

                    # Product image injection
                    if _has_product:
                        _p_mime = product_image_data.get("mime_type", "image/jpeg")
                        _p_b64  = product_image_data.get("base64_data", "")
                        contents.append({"inline_data": {"mime_type": _p_mime, "data": _p_b64}})
                        if _asset_count >= 2:
                            contents.append(
                                f"PRODUCT ASSET — '{product_name or 'the product'}': This is the TANGIBLE ANCHOR of the composite. "
                                f"Reproduce it with pixel accuracy — exact packaging, color, form, and design. "
                                f"Position it as the most sharply focused element, fully within frame. "
                                f"It is the thing the customer can buy and hold — make it irresistible."
                            )
                        else:
                            contents.append(
                                f"PRODUCT IMAGE — '{product_name or 'the product'}': Reproduce its exact form, color, texture, and design with precision. "
                                f"Feature it as the visual hero of the composition — fully within frame, sharply rendered."
                            )
                        logger.info(f"[PRODUCT_IMAGE] ✓ Product image injected: {product_name}")

                    # Service image injection
                    if _has_service:
                        _s_mime = service_image_data.get("mime_type", "image/jpeg")
                        _s_b64  = service_image_data.get("base64_data", "")
                        contents.append({"inline_data": {"mime_type": _s_mime, "data": _s_b64}})
                        if _asset_count >= 2:
                            contents.append(
                                f"SERVICE ASSET — '{service_name or 'the service'}': This is the EXPERIENTIAL LAYER of the composite. "
                                f"Use this image to define the atmosphere, environment, or transformation the customer experiences. "
                                f"It can occupy the background, a defined spatial zone, or be atmospherically blended into the scene — "
                                f"but it must remain clearly visible and recognisable as the service offering."
                            )
                        else:
                            contents.append(
                                f"SERVICE IMAGE — '{service_name or 'the service'}': Use this to define the visual treatment, atmosphere, and context. "
                                f"Feature it prominently as the experiential core of the composition."
                            )
                        logger.info(f"[SERVICE_IMAGE] ✓ Service image injected: {service_name}")

                    # Generate image
                    from google.genai import types
                    response = await gemini_client.aio.models.generate_content(
                        model=image_model,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            temperature=0.8,
                            response_modalities=["IMAGE"],
                            image_config=types.ImageConfig(
                                aspect_ratio=platform_spec['gemini_aspect']
                            )
                        )
                    )

                    # Log token usage with bulletproof handling
                    usage = getattr(response, 'usage_metadata', None)
                    if usage:
                        logger.info(f"Image Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

                    # Extract image with proper null checks
                    image_bytes = None

                    # Check if response has valid candidates
                    if not response.candidates or len(response.candidates) == 0:
                        logger.error(f"      [ERROR] No candidates in response for slide {img_num}")
                        # Check for blocked content
                        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                            logger.error(f"      [BLOCKED] Prompt feedback: {response.prompt_feedback}")
                        return None

                    candidate = response.candidates[0]

                    # Check if content exists
                    if not candidate.content:
                        logger.error(f"      [ERROR] No content in candidate for slide {img_num}")
                        # Check finish reason
                        if hasattr(candidate, 'finish_reason') and candidate.finish_reason:
                            logger.error(f"      [REASON] Finish reason: {candidate.finish_reason}")
                        if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                            logger.error(f"      [SAFETY] Safety ratings: {candidate.safety_ratings}")
                        return None

                    # Check if parts exist
                    if not candidate.content.parts:
                        logger.error(f"      [ERROR] No parts in content for slide {img_num}")
                        return None

                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data:
                            image_bytes = part.inline_data.data
                            break

                    if not image_bytes:
                        logger.error(f"      [ERROR] No image data extracted for slide {img_num}")
                        return None

                    # Save image
                    save_result = _save_smart_post_image(
                        image_bytes=image_bytes,
                        post_id=post_id,
                        company_name=company_name,
                        slide_number=img_num if num_images > 1 else None
                    )

                    # Create preview
                    image_preview = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"

                    logger.info(f"      [OK] Image {img_num} saved: {save_result['url']}")

                    return SmartPostImage(
                        image_url=save_result["url"],
                        image_preview=image_preview,
                        local_path=save_result["local_path"],
                        slide_number=img_num if num_images > 1 else None
                    )

                except Exception as e:
                    logger.error(f"      [ERROR] Image {img_num} failed: {e}")
                    logger.error(traceback.format_exc())
                    return None

            # ── LAYER 3: branched image generation ───────────────────────────
            if media_type == MediaType.image_carousel:
                # Sequential: each slide's output feeds as reference into the next
                logger.info(f"\n   [STEP 2] Generating {len(slides_plan)} slides sequentially (visual continuity)...")
                await queue.put({"step": "generating", "message": f"Preparing {len(slides_plan)} slides for your carousel..."})
                generated_images = []
                prev_bytes: Optional[bytes] = None
                _slide_seq = 0
                for slide_data in slides_plan:
                    img_obj, img_bytes = await _generate_carousel_slide(slide_data, visual_contract, prev_bytes)
                    if img_obj is not None:
                        generated_images.append(img_obj)
                        prev_bytes = img_bytes
                        _slide_seq += 1
                        await queue.put({
                            "step": "image_done",
                            "message": f"Preparing {_ordinal(_slide_seq)} image",
                            "sequence": _slide_seq,
                            "total": len(slides_plan),
                            "image_url": img_obj.image_url,
                        })
                    else:
                        logger.warning(f"   [STEP 2] Slide {slide_data.get('slide_number')} failed — skipped")
            else:
                # Single image / variants: parallel generation
                _is_multi_variant = num_images > 1
                _gen_msg = f"Preparing {num_images} variants..." if _is_multi_variant else "Preparing your image..."
                logger.info(f"\n   [STEP 2] {_gen_msg}")
                await queue.put({"step": "generating", "message": _gen_msg})
                smart_image_tasks = [_generate_single_smart_image(i) for i in range(1, num_images + 1)]
                smart_image_results = await asyncio.gather(*smart_image_tasks, return_exceptions=True)
                generated_images = []
                _img_seq = 0
                for result in smart_image_results:
                    if isinstance(result, Exception):
                        logger.error(f"      [ERROR] Image generation failed: {result}")
                    elif result is not None:
                        generated_images.append(result)
                        _img_seq += 1
                        _done_msg = f"Variant {_img_seq} of {num_images} ready" if _is_multi_variant else f"Preparing {_ordinal(_img_seq)} image"
                        await queue.put({
                            "step": "image_done",
                            "message": _done_msg,
                            "sequence": _img_seq,
                            "total": num_images,
                            "image_url": result.image_url,
                        })

            logger.info(f"      [IMAGES] {len(generated_images)}/{num_images} images generated successfully")

            # Captions were already generated in STEP 1 (reversed flow — before images)
            logger.info(f"\n   [CAPTIONS] Already generated in STEP 1: {len(captions)} caption(s)")

            # ═══════════════════════════════════════════════════════════════
            # SAVE METADATA
            # ═══════════════════════════════════════════════════════════════
            output_folder = ""
            if generated_images:
                output_folder = str(Path(generated_images[0].local_path).parent)

                # Save comprehensive metadata
                metadata_content = {
                    "post_id": post_id,
                    "posting_goal": posting_goal.value,
                    "content_mode": content_mode.value,
                    "media_type": media_type.value,
                    "company_name": company_name,
                    "company_description": company_description,
                    "website": website,
                    "tagline": tagline,
                    "brand_voice": brand_voice,
                    "brand_colors": brand_colors,
                    "target_platform": platform,
                    "custom_prompt": custom_prompt,
                    # Festival context (ensures image and caption alignment)
                    "festival_context": {
                        "name": festival_context.get("name"),
                        "greeting": festival_context.get("greeting"),
                        "themes": festival_context.get("themes"),
                        "formatted_date": festival_context.get("formatted_date"),
                        "detected_from_prompt": detected_festival_name is not None
                    } if festival_context else None,
                    # Brand voice parameters
                    "tone_attributes": tone_attributes,
                    "writing_style": writing_style,
                    "images": [
                        {
                            "url": img.image_url,
                            "local_path": img.local_path,
                            "slide_number": img.slide_number
                        }
                        for img in generated_images
                    ],
                    "captions": [
                        {
                            "caption": cap.caption,
                            "hashtags": cap.hashtags,
                            "variation_label": cap.variation_label
                        }
                        for cap in captions
                    ],
                    "generated_at": datetime.now().isoformat(),
                    "logo_included": logo_bytes is not None,
                    # "storage_type": "s3" if CAMPAIGN_S3_ENABLED else "local"
                    "storage_type": "local"
                }

                # ═══════════════════════════════════════════════════════════════
                # SAVE METADATA TO S3 OR LOCAL
                # ═══════════════════════════════════════════════════════════════
                # if CAMPAIGN_S3_ENABLED:
                #     # Upload metadata to S3
                #     sanitized_company = re.sub(r'[^\w\s-]', '', company_name.lower())
                #     sanitized_company = re.sub(r'[-\s]+', '_', sanitized_company)[:30]
                #     post_folder = f"{post_id[:8]}_{sanitized_company}"
                #     metadata_s3_key = f"smart_posts/{post_folder}/post_metadata.json"
                #     campaign_upload_json_to_s3(metadata_content, metadata_s3_key)
                #     logger.info(f"      [METADATA] Uploaded to S3: {metadata_s3_key}")
                # else:
                #     # Save locally
                #     metadata_file = Path(output_folder) / "post_metadata.json"
                #     with open(metadata_file, 'w', encoding='utf-8') as f:
                #         json.dump(metadata_content, f, indent=2, ensure_ascii=False)
                #     logger.info(f"      [METADATA] Saved to {metadata_file}")

                # ═══════════════════════════════════════════════════════════════
                # OLD LOCAL-ONLY METADATA CODE (COMMENTED OUT)
                # ═══════════════════════════════════════════════════════════════
                metadata_file = Path(output_folder) / "post_metadata.json"
                with open(metadata_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata_content, f, indent=2, ensure_ascii=False)
                
                logger.info(f"      [METADATA] Saved to {metadata_file}")
                # ═══════════════════════════════════════════════════════════════

            # ═══════════════════════════════════════════════════════════════
            # BUILD RESPONSE
            # ═══════════════════════════════════════════════════════════════
            logger.info(f"\n{'=' * 70}")
            logger.info(f"[SMART MODE] COMPLETE!")
            logger.info(f"Post ID: {post_id}")
            logger.info(f"Images: {len(generated_images)}")
            logger.info(f"Captions: {len(captions)}")
            logger.info(f"Output: {output_folder}")
            logger.info(f"{'=' * 70}")

            return SmartPostResponse(
                post_id=post_id,
                posting_goal=posting_goal.value,
                content_mode=content_mode.value,
                media_type=media_type.value,
                company_name=company_name,
                company_description=company_description,
                website=website,
                tagline=tagline,
                brand_voice=brand_voice,
                brand_colors=brand_colors,
                images=generated_images,
                captions=captions,
                output_folder=output_folder,
                generated_at=datetime.now().isoformat(),
                generation_summary={
                    "images_generated": len(generated_images),
                    "captions_generated": len(captions),
                    "target_platform": platform,
                    "logo_included": logo_bytes is not None,
                    "goal_context": goal_context,
                    # Festival info for alignment verification
                    "festival_used": festival_context.get("name") if festival_context else None,
                    "festival_detected_from_prompt": detected_festival_name is not None if festival_context else False,
                    "festival_greeting": festival_context.get("greeting") if festival_context else None,
                    # Brand voice parameters used
                    "tone_attributes_used": tone_attributes_list if tone_attributes_list else None,
                    "writing_style_used": writing_style is not None
                }
            )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[ERROR] Smart post generation failed: {e}")
            logger.error(traceback.format_exc())
            raise HTTPException(status_code=500, detail=f"Smart post generation failed: {str(e)}")

    @router.post("/smart-post")
    async def create_smart_post(
        # === COMPANY INFORMATION ===
        company_name: str = Form(..., description="Company/Brand name"),
        company_description: Optional[str] = Form(None, description="Brief description of the company"),
        website: Optional[str] = Form(None, description="Company website URL"),
        logo_file: Optional[UploadFile] = File(None, description="Company logo (PNG, JPG) — upload file"),
        logo_url: Optional[str] = Form(None, description="Public URL of company logo (PNG, JPG) — used when not uploading a file"),
        tagline: Optional[str] = Form(None, description="Company tagline/slogan"),
        brand_voice: Optional[str] = Form(None, description="Brand voice/tone (e.g., 'Professional', 'Friendly', 'Luxurious')"),
        brand_colors: Optional[str] = Form(None, description="Brand colors (e.g., 'Blue and White', '#1E90FF, #FFFFFF')"),

        # === BRAND VOICE & STYLE (for consistent messaging) ===
        tone_attributes: Optional[str] = Form(None, description="Comma-separated tone attributes (e.g., 'Professional, Friendly, Witty')"),
        writing_style: Optional[str] = Form(None, description="Writing style description (e.g., 'Short, punchy sentences with active voice')"),

        # === SMART MODE SETTINGS ===
        posting_goal: PostingGoal = Form(..., description="What do you want to achieve with this post?"),
        content_mode: ContentGenerationMode = Form(ContentGenerationMode.single_post, description="How should content be generated?"),
        media_type: MediaType = Form(MediaType.single_image, description="Type of media to generate"),

        # === OPTIONAL CONTEXT ===
        custom_prompt: Optional[str] = Form(None, description="Describe what you want — your creative direction, theme, or context. If uploading a reference image, describe who/what is in it here too (e.g., 'Happy Birthday banner for Rajesh Kumar, our Senior Engineer — warm, celebratory, gold and purple theme')."),
        target_platform: Optional[str] = Form("instagram", description="Primary target platform (instagram, facebook, linkedin, twitter)"),

        # === REFERENCE IMAGE (Optional — visual hero of the post) ===
        reference_image_file: Optional[UploadFile] = File(None, description="Upload a photo of the subject to feature in the post — person, product, scene, etc. Describe who/what it shows in the custom_prompt field."),
        reference_image_url: Optional[str] = Form(None, description="Public URL of a reference image to feature. Describe who/what it shows in the custom_prompt field."),

        # === PRODUCT (Optional) ===
        product_name: Optional[str] = Form(None, description="Product name to feature in the post"),
        product_description: Optional[str] = Form(None, description="Product description"),
        product_price: Optional[str] = Form(None, description="Product price (e.g., ₹999, $49.99)"),
        product_category: Optional[str] = Form(None, description="Product category"),
        product_features: Optional[str] = Form(None, description="Key product features (pipe-separated or comma-separated)"),
        product_benefits: Optional[str] = Form(None, description="Key product benefits (pipe-separated or comma-separated)"),
        product_image_file: Optional[UploadFile] = File(None, description="Product image file (PNG, JPG)"),
        product_image_url: Optional[str] = Form(None, description="Public URL of product image"),

        # === SERVICE (Optional) ===
        service_name: Optional[str] = Form(None, description="Service name to feature in the post"),
        service_description: Optional[str] = Form(None, description="Service description"),
        service_price: Optional[str] = Form(None, description="Service price"),
        service_duration: Optional[str] = Form(None, description="Service duration (e.g., '60 min', '3 months')"),
        service_category: Optional[str] = Form(None, description="Service category"),
        service_features: Optional[str] = Form(None, description="Key service features (pipe-separated or comma-separated)"),
        service_benefits: Optional[str] = Form(None, description="Key service benefits (pipe-separated or comma-separated)"),
        service_image_file: Optional[UploadFile] = File(None, description="Service image file (PNG, JPG)"),
        service_image_url: Optional[str] = Form(None, description="Public URL of service image"),

        # === VARIANTS / CAROUSEL SLIDES ===
        num_variants: int = Form(1, ge=1, le=10, description="Single Image: number of variants (1–5). Image Carousel: number of slides (2–10)."),
    ):
        """
        SMART MODE - Wizard-Style Post Creation

        A streamlined, intelligent post creation API that generates marketing content
        based on posting goals and content preferences.

        WORKFLOW:
        1. Provide company information (name, description, logo, colors, etc.)
        2. (OPTIONAL) Provide brand voice details (tone_attributes, writing_style)
        3. Select your posting goal (Promotional, Engagement, Announcement, etc.)
        4. Choose content generation mode (Single Post, A/B Variations, Multi-Slide)
        5. Get AI-generated images and captions tailored to your goals!

        BRAND VOICE PARAMETERS (for consistent messaging):
        - tone_attributes: Comma-separated (e.g., "Professional, Friendly, Witty")
        - writing_style: Description (e.g., "Short, punchy sentences with active voice")

        CONTENT MODES:
        - Single Post: 1 image + 1 caption
        - A/B Variations: 1 image + 3 caption variations (test which performs best)
        - Multi-Slide: 2-4 carousel images + 1 caption

        MEDIA TYPES:
        - Single Image: One marketing image
        - Image Carousel: 2-4 images for carousel posts

        PRODUCT IMAGE REFERENCE:
        Upload or provide URL of your actual product/service image for accurate
        product representation in generated marketing visuals.

        FESTIVAL/EVENT POSTS:
        When posting_goal is "Festival/Event", mention the festival name in
        custom_prompt (e.g., "Diwali", "Christmas", "Holi", "Eid").
        Gemini uses its own cultural knowledge to generate authentic visuals
        for any festival worldwide — no hardcoded database required.

        Async job-based API — returns a job_id immediately.
        Poll GET /smart-post/status/{job_id} to track progress and retrieve result.
        """
        # ── Read UploadFile bytes eagerly — MUST happen before background task ──
        logo_bytes: Optional[bytes] = None
        if logo_file:
            logo_bytes = await logo_file.read()
            logger.info(f"Logo uploaded: {logo_file.filename} ({len(logo_bytes)} bytes)")
        elif logo_url and logo_url.strip():
            try:
                import requests as _req
                _r = await asyncio.to_thread(_req.get, logo_url.strip(), timeout=15)
                if _r.status_code == 200 and _r.content:
                    logo_bytes = _r.content
                    logger.info(f"Logo fetched from URL: {logo_url} ({len(logo_bytes)} bytes)")
                else:
                    logger.warning(f"Failed to fetch logo from URL: status {_r.status_code}")
            except Exception as _e:
                logger.warning(f"Failed to fetch logo from URL: {_e}")

        reference_image_data: Optional[dict] = None
        if reference_image_file and reference_image_file.filename:
            try:
                file_content = await reference_image_file.read()
                reference_image_data = process_uploaded_reference_image(file_content, reference_image_file.filename)
                if reference_image_data and reference_image_data.get("success"):
                    logger.info(f"Reference image uploaded: {reference_image_file.filename} ({reference_image_data['file_size']} bytes)")
                else:
                    logger.warning("Reference image processing failed — continuing without reference")
                    reference_image_data = None
            except Exception as _e:
                logger.warning(f"Reference image upload error: {_e}")
        elif reference_image_url and reference_image_url.strip():
            try:
                reference_image_data = await asyncio.to_thread(download_reference_image, reference_image_url.strip())
                if reference_image_data and reference_image_data.get("success"):
                    logger.info(f"Reference image fetched from URL ({reference_image_data['file_size']} bytes)")
                else:
                    logger.warning("Reference image URL fetch failed — continuing without reference")
                    reference_image_data = None
            except Exception as _e:
                logger.warning(f"Reference image URL fetch error: {_e}")

        # ── Product image — eager read before background task ─────────────────
        product_image_data: Optional[dict] = None
        if product_image_file and product_image_file.filename:
            try:
                _fc = await product_image_file.read()
                product_image_data = process_uploaded_reference_image(_fc, product_image_file.filename)
                if not (product_image_data and product_image_data.get("success")):
                    logger.warning("Product image processing failed — continuing without product image")
                    product_image_data = None
                else:
                    logger.info(f"Product image uploaded: {product_image_file.filename} ({product_image_data['file_size']} bytes)")
            except Exception as _e:
                logger.warning(f"Product image upload error: {_e}")
        elif product_image_url and product_image_url.strip():
            try:
                product_image_data = await asyncio.to_thread(download_reference_image, product_image_url.strip())
                if not (product_image_data and product_image_data.get("success")):
                    logger.warning("Product image URL fetch failed — continuing without product image")
                    product_image_data = None
                else:
                    logger.info(f"Product image fetched from URL ({product_image_data['file_size']} bytes)")
            except Exception as _e:
                logger.warning(f"Product image URL fetch error: {_e}")

        # ── Service image — eager read before background task ─────────────────
        service_image_data: Optional[dict] = None
        if service_image_file and service_image_file.filename:
            try:
                _fc = await service_image_file.read()
                service_image_data = process_uploaded_reference_image(_fc, service_image_file.filename)
                if not (service_image_data and service_image_data.get("success")):
                    logger.warning("Service image processing failed — continuing without service image")
                    service_image_data = None
                else:
                    logger.info(f"Service image uploaded: {service_image_file.filename} ({service_image_data['file_size']} bytes)")
            except Exception as _e:
                logger.warning(f"Service image upload error: {_e}")
        elif service_image_url and service_image_url.strip():
            try:
                service_image_data = await asyncio.to_thread(download_reference_image, service_image_url.strip())
                if not (service_image_data and service_image_data.get("success")):
                    logger.warning("Service image URL fetch failed — continuing without service image")
                    service_image_data = None
                else:
                    logger.info(f"Service image fetched from URL ({service_image_data['file_size']} bytes)")
            except Exception as _e:
                logger.warning(f"Service image URL fetch error: {_e}")

        # ── Create job + queue, fire background task, return job_id immediately ─
        job_id = str(uuid.uuid4())
        queue: asyncio.Queue = asyncio.Queue()
        job_store[job_id] = {"status": "processing", "queue": queue}
        logger.info(f"[WS] Smart post job created: {job_id}  company='{company_name}'")

        async def _run_job():
            try:
                result = await _smart_post_impl(
                    company_name=company_name,
                    company_description=company_description,
                    website=website,
                    logo_bytes=logo_bytes,
                    tagline=tagline,
                    brand_voice=brand_voice,
                    brand_colors=brand_colors,
                    tone_attributes=tone_attributes,
                    writing_style=writing_style,
                    posting_goal=posting_goal,
                    content_mode=content_mode,
                    media_type=media_type,
                    custom_prompt=custom_prompt,
                    target_platform=target_platform,
                    reference_image_data=reference_image_data,
                    queue=queue,
                    product_name=product_name,
                    product_description=product_description,
                    product_price=product_price,
                    product_category=product_category,
                    product_features=product_features,
                    product_benefits=product_benefits,
                    product_image_data=product_image_data,
                    service_name=service_name,
                    service_description=service_description,
                    service_price=service_price,
                    service_duration=service_duration,
                    service_category=service_category,
                    service_features=service_features,
                    service_benefits=service_benefits,
                    service_image_data=service_image_data,
                    num_variants=num_variants,
                )
                _result_dict = result.model_dump()
                job_store[job_id]["status"] = "done"
                job_store[job_id]["result"] = _result_dict
                _persist_smartpost_job(job_id, {"status": "done", "result": _result_dict})
                await queue.put({"step": "done", "message": "Completed", "result": _result_dict})
                asyncio.create_task(_cleanup_smartpost_job(job_id))
                logger.info(f"[WS] Smart post job {job_id[:8]} completed")
            except (Exception, asyncio.CancelledError) as e:
                job_store[job_id]["status"] = "error"
                job_store[job_id]["error"] = str(e)
                _persist_smartpost_job(job_id, {"status": "error", "error": str(e)})
                await queue.put({
                    "step": "error",
                    "message": "Smart post generation failed. Please try again.",
                    "error": str(e),
                })
                asyncio.create_task(_cleanup_smartpost_job(job_id))
                logger.error(f"[WS] Smart post job {job_id[:8]} failed: {e}")

        asyncio.create_task(_run_job())

        return {
            "job_id": job_id,
            "status": "processing",
            "message": f"Smart post started. Connect to /ws/smart-post/{job_id} for real-time progress.",
        }

    # ═══════════════════════════════════════════════════════════════════════════
    # WEBSOCKET — real-time smart post progress stream
    # ═══════════════════════════════════════════════════════════════════════════
    @router.websocket("/ws/smart-post/{job_id}")
    async def ws_smart_post_status(websocket: WebSocket, job_id: str):
        """
        Stream smart post generation progress.

        Messages pushed by the server:
          {"step": "started",    "message": "Generating smart post for {company}"}
          {"step": "planning",   "message": "Planning your X-slide carousel..."}
          {"step": "captions",   "message": "Generating captions..."}
          {"step": "generating", "message": "Preparing your image(s)..."}
          {"step": "image_done", "message": "Preparing Nth image", "sequence": N, "total": N, "image_url": "..."}
          {"step": "done",       "message": "Completed", "result": { full SmartPostResponse dict }}
          {"step": "error",      "message": "...", "error": "...details..."}
        """
        await websocket.accept()

        for _ in range(20):
            if job_id in job_store:
                break
            await asyncio.sleep(0.15)

        if job_id not in job_store:
            # Check file — handles reconnects after completion
            saved = _read_persisted_smartpost_job(job_id)
            if saved and saved.get("status") == "done":
                await websocket.send_json({"step": "done", "message": "Completed", "result": saved["result"]})
                await websocket.close(code=1000)
            elif saved and saved.get("status") == "error":
                await websocket.send_json({"step": "error", "message": "Smart post generation failed.", "error": saved.get("error", "Unknown error")})
                await websocket.close(code=1000)
            else:
                await websocket.send_json({"step": "error", "error": f"Invalid job_id: {job_id}"})
                await websocket.close(code=1008)
            return

        q: asyncio.Queue = job_store[job_id]["queue"]
        try:
            while True:
                message = await q.get()
                await websocket.send_json(message)
                if message.get("step") in ("done", "error"):
                    break
        except WebSocketDisconnect:
            logger.info(f"[WS] Client disconnected from smart post job {job_id}")
        finally:
            try:
                await websocket.close(code=1000)
            except Exception:
                pass

    # ═══════════════════════════════════════════════════════════════════════════
    # [SMART SCRAPE] INTELLIGENT WEBSITE SCRAPING API

    return router