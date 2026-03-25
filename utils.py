from datetime import datetime
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageFilter
from typing import Optional, Dict, List, Any
import json
import re
import base64
import logging
import traceback
import os
import requests

from models import (
    CAMPAIGN_PLATFORM_SPECS,
    ProductFeature, ServiceBenefit, ServiceSkill,
)
from prompt_guards import CAPTION_ENRICHMENT_DIRECTIVE

logger = logging.getLogger(__name__)


# ===============================================================================
# GEMINI HELPERS
# ===============================================================================

def extract_gemini_text(response, context: str = "Gemini") -> str:
    """
    Bulletproof text extraction from Gemini response.
    Handles all edge cases: empty responses, blocked prompts, safety filters.

    Args:
        response: The Gemini API response object
        context: Description for logging (e.g., "caption generation", "analysis")

    Returns:
        str: Extracted text content

    Raises:
        ValueError: If no text could be extracted
    """
    response_text = None

    # Try direct .text attribute first (most common case)
    if hasattr(response, 'text') and response.text:
        response_text = response.text.strip()
    # Fallback: extract from candidates -> content -> parts
    elif hasattr(response, 'candidates') and response.candidates:
        candidate = response.candidates[0]
        if hasattr(candidate, 'content') and candidate.content:
            if hasattr(candidate.content, 'parts') and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, 'text') and part.text:
                        response_text = part.text.strip()
                        break

    # If still no text, log detailed error info and raise
    if not response_text:
        logger.error(f"[ERROR] Gemini returned empty response for {context}")

        # Log prompt feedback if available (indicates safety block)
        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            logger.error(f"[BLOCKED] Prompt feedback: {response.prompt_feedback}")

        # Log candidate finish reason if available
        if hasattr(response, 'candidates') and response.candidates:
            candidate = response.candidates[0]
            if hasattr(candidate, 'finish_reason') and candidate.finish_reason:
                logger.error(f"[REASON] Finish reason: {candidate.finish_reason}")
            if hasattr(candidate, 'safety_ratings') and candidate.safety_ratings:
                logger.error(f"[SAFETY] Safety ratings: {candidate.safety_ratings}")

        raise ValueError(f"Empty response from Gemini for {context}")

    return response_text


def log_gemini_usage(response, context: str = ""):
    """Log Gemini token usage if available."""
    usage = getattr(response, 'usage_metadata', None)
    if usage:
        prompt_tokens = getattr(usage, 'prompt_token_count', '?')
        output_tokens = getattr(usage, 'candidates_token_count', '?')
        logger.info(f"{context}Tokens: prompt={prompt_tokens} output={output_tokens}")


# ===============================================================================
# FESTIVAL FUNCTIONS — removed (will be replaced with a calendar API)
# ===============================================================================



def parse_product_features(features_data: list) -> List[ProductFeature]:
    """
    Parse product features - handles both formats:
    - List of strings: ["Feature 1", "Feature 2"]
    - List of dicts: [{"title": "Feature 1", "description": "..."}]
    """
    if not features_data:
        return []

    result = []
    for item in features_data:
        try:
            if isinstance(item, str):
                # Handle string format
                if item.strip():
                    result.append(ProductFeature(title=item.strip(), description=None))
            elif isinstance(item, dict):
                # Handle dict format
                title = item.get('title') or item.get('name') or item.get('feature', '')
                if title:
                    result.append(ProductFeature(
                        title=str(title).strip(),
                        description=item.get('description')
                    ))
            else:
                # Try to convert to string
                str_val = str(item).strip()
                if str_val:
                    result.append(ProductFeature(title=str_val, description=None))
        except Exception as e:
            logger.warning(f"[PARSE] Skipping invalid feature item: {item}, error: {e}")
            continue

    return result if result else None


def parse_service_benefits(benefits_data: list) -> List[ServiceBenefit]:
    """
    Parse service benefits - handles both formats:
    - List of strings: ["Benefit 1", "Benefit 2"]
    - List of dicts: [{"title": "Benefit 1", "description": "..."}]
    """
    if not benefits_data:
        return []

    result = []
    for item in benefits_data:
        try:
            if isinstance(item, str):
                # Handle string format
                if item.strip():
                    result.append(ServiceBenefit(title=item.strip(), description=None))
            elif isinstance(item, dict):
                # Handle dict format
                title = item.get('title') or item.get('name') or item.get('benefit', '')
                if title:
                    result.append(ServiceBenefit(
                        title=str(title).strip(),
                        description=item.get('description')
                    ))
            else:
                # Try to convert to string
                str_val = str(item).strip()
                if str_val:
                    result.append(ServiceBenefit(title=str_val, description=None))
        except Exception as e:
            logger.warning(f"[PARSE] Skipping invalid benefit item: {item}, error: {e}")
            continue

    return result if result else None


def parse_service_skills(skills_data: list) -> List[ServiceSkill]:
    """
    Parse service skills - handles both formats:
    - List of strings: ["Python", "JavaScript"]
    - List of dicts: [{"skill_name": "Python", "level": "Expert"}]
    """
    if not skills_data:
        return []

    result = []
    for item in skills_data:
        try:
            if isinstance(item, str):
                # Handle string format
                if item.strip():
                    result.append(ServiceSkill(skill_name=item.strip(), level=None))
            elif isinstance(item, dict):
                # Handle dict format - try multiple key names
                skill_name = (
                    item.get('skill_name') or
                    item.get('name') or
                    item.get('skill') or
                    item.get('title', '')
                )
                if skill_name:
                    result.append(ServiceSkill(
                        skill_name=str(skill_name).strip(),
                        level=item.get('level') or item.get('proficiency')
                    ))
            else:
                # Try to convert to string
                str_val = str(item).strip()
                if str_val:
                    result.append(ServiceSkill(skill_name=str_val, level=None))
        except Exception as e:
            logger.warning(f"[PARSE] Skipping invalid skill item: {item}, error: {e}")
            continue

    return result if result else None



# ===============================================================================
# IMAGE PROCESSING
# ===============================================================================

def resize_image_for_platform(image_bytes: bytes, target_width: int, target_height: int) -> bytes:
    """
    Resize image to platform specifications using blur-fill letterbox.

    Instead of center-cropping (which destroys content), this scales the original
    image to fully fit within the target canvas and fills any remaining space with
    a blurred version of the image. No content is ever lost.

    Example: 1024x1024 square → 1200x628 Facebook
      - Old: center-crop loses 44% of height
      - New: scales to 628x628 centered on a blurred 1200x628 background
    """
    try:
        img = Image.open(BytesIO(image_bytes)).convert("RGB")
        img_w, img_h = img.size
        target_ratio = target_width / target_height
        img_ratio = img_w / img_h

        # If the ratios already match (within 3%), just resize directly — no padding needed
        if abs(img_ratio - target_ratio) / target_ratio < 0.03:
            resized = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
            output = BytesIO()
            resized.save(output, format='PNG', optimize=True)
            return output.getvalue()

        # ── Blur-fill letterbox ──────────────────────────────────────────────
        # 1. Stretch original to fill the full canvas, then heavily blur it
        background = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
        background = background.filter(ImageFilter.GaussianBlur(radius=24))

        # 2. Scale foreground to FIT within the canvas (no cropping)
        scale = min(target_width / img_w, target_height / img_h)
        fg_w = int(img_w * scale)
        fg_h = int(img_h * scale)
        foreground = img.resize((fg_w, fg_h), Image.Resampling.LANCZOS)

        # 3. Center the sharp foreground on the blurred background
        x_off = (target_width - fg_w) // 2
        y_off = (target_height - fg_h) // 2
        background.paste(foreground, (x_off, y_off))

        output = BytesIO()
        background.save(output, format='PNG', optimize=True)
        return output.getvalue()

    except Exception as e:
        logger.error(f"Image resize failed: {e}")
        return image_bytes


def save_campaign_image(
    image_bytes: bytes,
    campaign_id: str,
    campaign_name: str,
    platform: str,
    item_name: str,
    post_number: int,
    storage_dir: Path
) -> Dict[str, str]:
    """Save campaign image to S3 (production) or local folder (fallback)"""
    now = datetime.now()

    # Create campaign-specific folder: campaigns/{campaign_id}_{campaign_name}/
    sanitized_campaign_name = re.sub(r'[^\w\s-]', '', campaign_name.lower())
    sanitized_campaign_name = re.sub(r'[-\s]+', '_', sanitized_campaign_name)[:30]
    campaign_folder = f"{campaign_id[:8]}_{sanitized_campaign_name}"

    # Filename: post_{number}_{platform}_{item_name}.png
    sanitized_item = re.sub(r'[^\w\s-]', '', item_name.lower())
    sanitized_item = re.sub(r'[-\s]+', '_', sanitized_item)[:20]
    filename = f"post_{post_number}_{platform}_{sanitized_item}.png"

    organized_path = storage_dir / "campaigns" / campaign_folder
    organized_path.mkdir(parents=True, exist_ok=True)

    file_path = organized_path / filename
    with open(file_path, "wb") as f:
        f.write(image_bytes)

    relative_path = f"campaigns/{campaign_folder}/{filename}"
    return {
        "local_path": str(file_path),
        "url": f"/images/{relative_path}",
        "campaign_folder": str(organized_path)
    }


# ===============================================================================
# REFERENCE IMAGE HANDLING
# ===============================================================================

def download_reference_image(image_url: str, timeout: int = 15) -> Optional[Dict[str, Any]]:
    """
    Download and process a reference image from URL for use in AI generation.

    This function downloads product/service images and prepares them for use
    as visual references in Gemini's image generation, enabling the AI to
    create marketing content that accurately represents the actual product.

    Args:
        image_url: URL of the product/service image
        timeout: Request timeout in seconds

    Returns:
        Dict containing:
            - success: bool
            - image_bytes: raw image data (bytes)
            - mime_type: detected MIME type
            - dimensions: (width, height) tuple
            - file_size: size in bytes
            - base64_data: base64 encoded string for Gemini API
        Or None if download fails
    """
    if not image_url or not image_url.strip():
        return None

    try:
        logger.info(f"[REF_IMAGE] Downloading reference image: {image_url[:80]}...")

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': image_url  # Some CDNs require referer
        }

        response = requests.get(image_url, headers=headers, timeout=timeout, stream=True)

        if response.status_code != 200:
            logger.warning(f"[REF_IMAGE] Failed to download: HTTP {response.status_code}")
            return None

        # Check content type
        content_type = response.headers.get('content-type', '').lower()

        # Determine MIME type
        if 'png' in content_type or image_url.lower().endswith('.png'):
            mime_type = 'image/png'
        elif 'webp' in content_type or image_url.lower().endswith('.webp'):
            mime_type = 'image/webp'
        elif 'gif' in content_type or image_url.lower().endswith('.gif'):
            mime_type = 'image/gif'
        elif 'svg' in content_type or image_url.lower().endswith('.svg'):
            # SVG needs conversion for Gemini - skip for now
            logger.warning(f"[REF_IMAGE] SVG format not supported as reference image")
            return None
        else:
            # Default to JPEG
            mime_type = 'image/jpeg'

        image_bytes = response.content
        file_size = len(image_bytes)

        # Validate it's actually an image and get dimensions
        try:
            img = Image.open(BytesIO(image_bytes))
            width, height = img.size

            # Convert to RGB if needed (for proper processing)
            if img.mode in ('RGBA', 'P'):
                # Convert to RGB with white background
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'RGBA':
                    rgb_img.paste(img, mask=img.split()[3])  # Use alpha channel as mask
                else:
                    rgb_img.paste(img)
                img = rgb_img

                # Re-encode as PNG for better quality
                buffer = BytesIO()
                img.save(buffer, format='PNG', quality=95)
                image_bytes = buffer.getvalue()
                mime_type = 'image/png'

            img.close()

        except Exception as e:
            logger.warning(f"[REF_IMAGE] Failed to process image: {e}")
            return None

        # Check file size (Gemini has limits)
        max_size = 20 * 1024 * 1024  # 20MB limit
        if file_size > max_size:
            logger.warning(f"[REF_IMAGE] Image too large ({file_size / 1024 / 1024:.1f}MB), resizing...")

            # Resize to reduce file size
            img = Image.open(BytesIO(image_bytes))

            # Calculate new size maintaining aspect ratio
            max_dimension = 2048
            ratio = min(max_dimension / width, max_dimension / height)
            if ratio < 1:
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                width, height = new_width, new_height

            # Re-encode with compression
            buffer = BytesIO()
            if mime_type == 'image/png':
                img.save(buffer, format='PNG', optimize=True)
            else:
                img.save(buffer, format='JPEG', quality=85, optimize=True)
                mime_type = 'image/jpeg'

            image_bytes = buffer.getvalue()
            file_size = len(image_bytes)
            img.close()

        # Create base64 for Gemini API
        base64_data = base64.b64encode(image_bytes).decode('utf-8')

        logger.info(f"[REF_IMAGE] ✓ Downloaded: {width}x{height}, {file_size/1024:.1f}KB, {mime_type}")

        return {
            "success": True,
            "image_bytes": image_bytes,
            "mime_type": mime_type,
            "dimensions": (width, height),
            "file_size": file_size,
            "base64_data": base64_data,
            "source_url": image_url
        }

    except requests.Timeout:
        logger.warning(f"[REF_IMAGE] Timeout downloading: {image_url[:50]}...")
        return None
    except requests.RequestException as e:
        logger.warning(f"[REF_IMAGE] Request error: {e}")
        return None
    except Exception as e:
        logger.error(f"[REF_IMAGE] Unexpected error: {e}")
        return None


def process_uploaded_reference_image(file_content: bytes, filename: str) -> Optional[Dict[str, Any]]:
    """
    Process an uploaded reference image file.

    Args:
        file_content: Raw file bytes
        filename: Original filename for MIME type detection

    Returns:
        Dict with processed image data or None if invalid
    """
    try:
        # Detect MIME type from filename
        filename_lower = filename.lower()
        if filename_lower.endswith('.png'):
            mime_type = 'image/png'
        elif filename_lower.endswith('.webp'):
            mime_type = 'image/webp'
        elif filename_lower.endswith('.gif'):
            mime_type = 'image/gif'
        elif filename_lower.endswith(('.jpg', '.jpeg')):
            mime_type = 'image/jpeg'
        else:
            mime_type = 'image/png'  # Default

        # Validate and process image
        img = Image.open(BytesIO(file_content))
        width, height = img.size

        # Convert RGBA/P to RGB
        if img.mode in ('RGBA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                rgb_img.paste(img, mask=img.split()[3])
            else:
                rgb_img.paste(img)
            img = rgb_img

            buffer = BytesIO()
            img.save(buffer, format='PNG', quality=95)
            file_content = buffer.getvalue()
            mime_type = 'image/png'

        # Check and resize if too large
        file_size = len(file_content)
        max_size = 20 * 1024 * 1024

        if file_size > max_size or width > 4096 or height > 4096:
            max_dimension = 2048
            ratio = min(max_dimension / width, max_dimension / height, 1.0)
            if ratio < 1:
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                width, height = new_width, new_height

            buffer = BytesIO()
            img.save(buffer, format='PNG', optimize=True)
            file_content = buffer.getvalue()
            file_size = len(file_content)
            mime_type = 'image/png'

        img.close()

        base64_data = base64.b64encode(file_content).decode('utf-8')

        logger.info(f"[REF_IMAGE] ✓ Processed upload: {width}x{height}, {file_size/1024:.1f}KB")

        return {
            "success": True,
            "image_bytes": file_content,
            "mime_type": mime_type,
            "dimensions": (width, height),
            "file_size": file_size,
            "base64_data": base64_data,
            "source": "upload"
        }

    except Exception as e:
        logger.error(f"[REF_IMAGE] Failed to process upload: {e}")
        return None


def build_product_image_context(
    reference_image: Dict[str, Any],
    item_name: str,
    item_type: str
) -> List[Any]:
    """
    Build Gemini API content array with product reference image.

    This creates the optimal prompt structure for Gemini to use
    a product image as visual reference for marketing content generation.

    Args:
        reference_image: Dict from download_reference_image()
        item_name: Product/service name
        item_type: "product" or "service"

    Returns:
        List of content items for Gemini API
    """
    if not reference_image or not reference_image.get("success"):
        return []

    return [
        {
            "inline_data": {
                "mime_type": reference_image["mime_type"],
                "data": reference_image["base64_data"]
            }
        },
        f"""
═══════════════════════════════════════════════════════════════════════════════
🖼️ PRODUCT REFERENCE IMAGE - CRITICAL VISUAL GUIDE
═══════════════════════════════════════════════════════════════════════════════

The image above is the ACTUAL {item_type.upper()}: "{item_name}"

IMPORTANT INSTRUCTIONS FOR IMAGE GENERATION:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. VISUAL ACCURACY (CRITICAL):
   • Study this reference image carefully - this is the REAL product
   • Maintain accurate colors, shapes, and proportions
   • The generated image should make viewers RECOGNIZE this exact product
   • DO NOT create a generic/different looking product

2. PRODUCT SHOWCASE APPROACH:
   • Feature the product prominently as the hero element
   • Use professional product photography lighting techniques
   • Create depth and dimension that highlights product quality
   • Show the product from its most appealing angle

3. MARKETING CONTEXT:
   • Place the product in an aspirational lifestyle context
   • Add subtle environmental elements that enhance appeal
   • Create emotional connection through visual storytelling
   • Ensure the product looks premium and desirable

4. QUALITY STANDARDS:
   • Generate photorealistic, high-quality marketing imagery
   • Ensure crisp details and professional composition
   • The output should look like a premium advertising campaign
   • Match or exceed the quality of the reference image

5. BRAND INTEGRATION:
   • Seamlessly incorporate any provided logo
   • Maintain consistent brand colors and aesthetics
   • Balance product focus with brand messaging

6. COMPOSITION RULES (CRITICAL):
   • Render marketing text as designed typographic elements — bold headline, clean subline.
   • Balance the product hero with the text placement — text should not obscure the product.
   • Focus on product, environment, and integrated brand messaging.

═══════════════════════════════════════════════════════════════════════════════
"""
    ]


# ===============================================================================
# CAPTION GENERATION
# ===============================================================================

async def generate_caption_and_hashtags(
    item_name: str,
    item_type: str,
    item_description: Optional[str],
    item_price: Optional[str],
    platform: str,
    platform_spec: Dict[str, Any],
    company_name: Optional[str],
    brand_voice: Optional[str],
    campaign_goal: str,
    gemini_client,
    gemini_model: str,
    tagline: Optional[str] = None,
    campaign_goal_direction: Optional[str] = None,
    content_type_direction: Optional[str] = None
) -> tuple:
    """
    Generate platform-optimized caption, hashtags, AND display_text in one AI call.
    The display_text will be rendered as an image and embedded into Gemini for image generation.

    Returns: (caption, hashtags, display_text)
    """

    prompt = f"""
You are an expert social media marketing copywriter AND marketing designer with 20+ years experience.

DUAL TASK — Generate ALL THREE in a single response:
1. An engaging {platform_spec['name']} post caption
2. Relevant hashtags
3. A short, impactful DISPLAY TEXT for the marketing image

{CAPTION_ENRICHMENT_DIRECTIVE}

WHAT WE'RE PROMOTING:
- Type: {item_type.upper()}
- Name: {item_name}
- Description: {item_description or f'Premium {item_type}'}
- Price: {item_price or 'Contact for pricing'}

BRAND INFO:
- Company: {company_name or 'Our Brand'}
- Voice/Tone: {brand_voice or 'professional yet friendly'}
- Campaign Goal: {campaign_goal}
{f"- Tagline: {tagline}" if tagline else ""}

{f"CAMPAIGN GOAL DIRECTIVE:{chr(10)}{campaign_goal_direction}{chr(10)}" if campaign_goal_direction else ""}
{f"CONTENT TYPE DIRECTIVE:{chr(10)}{content_type_direction}{chr(10)}" if content_type_direction else ""}
PLATFORM: {platform_spec['name']}
- Tone: {platform_spec['tone']}
- Style: {platform_spec['caption_style']}
- Hashtag count: {platform_spec['hashtag_count']}

PART 1 — CAPTION REQUIREMENTS:
1. Caption should be 1-2 sentences — it deepens the story beyond what is shown on the image
2. Open with a scroll-stopping hook — the first line must grab attention instantly
3. Clearly communicate the value proposition, key features, and benefits
4. Include a compelling, natural call-to-action
5. Include price/offer details if available — these are NOT on the image
6. Match the platform's tone and style
7. Hashtags should mix popular + niche tags
8. All hashtags lowercase with # prefix
9. Use all the provided information effectively

PART 2 — DISPLAY TEXT FOR IMAGE (CRITICAL):
Generate impactful marketing text that will be rendered ON the marketing image.
This is a TEXT-HEAVY marketing image!
Format: HEADLINE | SUBLINE | KEY FEATURE (use | as separator)
Rules:
- HEADLINE: 3-6 impactful words — a compelling hook or brand statement (NOT just the product name alone)
- SUBLINE: 5-12 words — clearly explain WHAT the product/service does or its key benefit so a reader instantly understands the offering
- KEY FEATURE: 3-8 words — one standout feature, price point, CTA, or unique selling point
- The reader should understand the company/product/service just from reading the image text
- Do NOT just repeat the product name — add context, value, or emotion
- Must be grammatically PERFECT — zero errors
- Must be SEMANTICALLY ALIGNED with the caption
- Think like a professional brand poster: headline grabs attention, subline informs clearly, feature convinces to act

RESPOND WITH VALID JSON ONLY:
{{
    "caption": "Your engaging caption here with emojis if appropriate for the platform...",
    "hashtags": ["#hashtag1", "#hashtag2", "#hashtag3"],
    "display_text": "HEADLINE | SUBLINE | KEY FEATURE"
}}

NO markdown, NO explanation, ONLY the JSON object.
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
            logger.error("[ERROR] Gemini returned empty response for caption")
            if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
                logger.error(f"[BLOCKED] Prompt feedback: {response.prompt_feedback}")
            raise ValueError("Empty response from Gemini")

        usage = getattr(response, 'usage_metadata', None)
        if usage:
            logger.info(f"Tokens: prompt={getattr(usage, 'prompt_token_count', '?')} output={getattr(usage, 'candidates_token_count', '?')}")

        logger.info(f"Caption raw response length: {len(response_text)} chars")

        # Clean markdown code blocks if present
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        # Try to find JSON object in response
        if not response_text.startswith("{"):
            # Try to extract JSON from text
            start_idx = response_text.find("{")
            end_idx = response_text.rfind("}") + 1
            if start_idx != -1 and end_idx > start_idx:
                response_text = response_text[start_idx:end_idx]

        result = json.loads(response_text)
        caption = result.get("caption", "")
        hashtags = result.get("hashtags", [])
        display_text = result.get("display_text", "")

        # Validate we got actual content
        if not caption or len(caption) < 10:
            raise ValueError("Caption too short or empty")

        # Ensure hashtags have # prefix
        hashtags = [f"#{tag.lstrip('#')}" for tag in hashtags][:platform_spec['hashtag_count']]

        # Clean display_text
        if display_text:
            display_text = display_text.strip().strip('"\'')
            logger.info(f"Display text generated: {display_text}")
        else:
            # Fallback display_text
            display_text = f"{item_name} | {tagline or 'Excellence You Deserve'} | Learn More"
            logger.info(f"Display text fallback: {display_text}")

        logger.info(f"Caption generated: {caption[:60]}...")
        logger.info(f"Hashtags: {hashtags}")

        return caption, hashtags, display_text

    except Exception as e:
        logger.error(f"      Caption generation error: {e}")
        logger.error(f"      Response was: {response_text[:500] if 'response_text' in dir() else 'N/A'}")

        # Generate smart fallback caption based on context
        if item_type == "product":
            default_caption = f"Introducing {item_name}! {item_description or 'Discover quality and innovation.'}"
            if item_price:
                default_caption += f" Now available at {item_price}."
            default_caption += " Shop now and experience the difference!"
        elif item_type == "service":
            default_caption = f"Transform your experience with {item_name}! {item_description or 'Professional service you can trust.'}"
            if item_price:
                default_caption += f" Starting from {item_price}."
            default_caption += " Book your appointment today!"
        else:
            default_caption = f"Discover {company_name or 'our brand'}! {item_description or 'Excellence in everything we do.'}"
            default_caption += " Follow us for more updates!"

        # Generate relevant hashtags
        item_tag = item_name.lower().replace(" ", "").replace("-", "")[:15]
        company_tag = (company_name or "brand").lower().replace(" ", "").replace("-", "")[:15]
        default_hashtags = [
            f"#{item_tag}",
            f"#{company_tag}",
            f"#{platform}",
            f"#{item_type}",
            "#marketing",
            "#business"
        ][:platform_spec['hashtag_count']]

        # Fallback display_text
        default_display = f"{item_name} | {tagline or 'Quality You Deserve'} | Discover More"

        return default_caption, default_hashtags, default_display



# ===============================================================================
# COMPANY ANALYSIS
# ===============================================================================

def generate_brand_awareness_items(
    analysis: Dict[str, Any],
    company_name: str
) -> List[Dict]:
    """
    [CONVERT] Convert company analysis into campaign items
    
    Takes the smart company understanding and creates "virtual products/services"
    that represent key brand messages and values.
    
    These become the items_to_promote for the campaign.
    
    Args:
        analysis: Output from hybrid_company_understanding()
        company_name: Company name for logging
    
    Returns:
        List of items with type, name, description, etc.
    """
    
    logger.info(f"[GENERATE] Generating {len(analysis.get('campaign_themes', []))} campaign items for {company_name}")
    
    items = []
    
    for theme in analysis.get("campaign_themes", []):
        item = {
            "type": "brand_theme",
            "name": theme.get("theme_name", "Campaign"),
            "description": theme.get("focus", "Brand campaign"),
            "key_message": theme.get("key_message", ""),
            "visual_tone": theme.get("visual_tone", "Professional"),
            "category": "Brand Awareness",
            "subcategory": "Company Theme",
            "tags": ["brand", "awareness", company_name.lower()],
            "price": None,
            "sku": None,
            "features": None,
            "benefits": None,
            "image_url": None,
            "post_percentage": theme.get("allocation_percent", 20),
        }
        
        items.append(item)
        logger.info(f"   + {item['name']}: {item['post_percentage']}%")
    
    return items


# ===============================================================================
# COMPANY UNDERSTANDING — Gemini Knowledge Base
# ===============================================================================

async def hybrid_company_understanding(
    gemini_client,
    gemini_model: str,
    company_name: str,
    company_description: str,
    website: str,
    tagline: str,
    brand_voice: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze company information via Gemini and generate 5 strategic campaign themes.

    Args:
        gemini_client: Gemini API client
        gemini_model: Model name
        company_name: Company name
        company_description: Company description
        website: Company website (informational only)
        tagline: Company tagline
        brand_voice: Brand voice/tone (optional)

    Returns:
        Comprehensive company analysis Dict with campaign themes
    """
    logger.info(f"[COMPANY] Analyzing company via Gemini: {company_name}")

    prompt = f"""You are an ELITE marketing strategist with 25+ years of experience analyzing companies and creating strategic campaign frameworks.

Analyze this company and create a COMPREHENSIVE, STRATEGIC company analysis with 5 brilliant campaign themes.

═══════════════════════════════════════════════════════════════════════════
COMPANY INFORMATION
═══════════════════════════════════════════════════════════════════════════
Company Name: {company_name}
Description: {company_description}
Tagline: {tagline}
{f'Brand Voice: {brand_voice}' if brand_voice else ''}
Website: {website if website else 'Not provided'}

═══════════════════════════════════════════════════════════════════════════
YOUR TASK: Create a Strategic Company Analysis
═══════════════════════════════════════════════════════════════════════════

1. UNDERSTAND THE COMPANY:
   - What industry are they truly in?
   - What is their core business model?
   - Who is their target audience?
   - What are their main services/products?
   - How do they differentiate from competitors?
   - What are their key brand values?

2. GENERATE 5 BRILLIANT CAMPAIGN THEMES:
   - Each theme should be UNIQUE and highlight different aspects
   - Themes should be SPECIFIC to this company, not generic
   - Each theme represents a key marketing angle
   - Examples:
     * If Nike: "Athletic Achievement", "Innovation Story", "Community Empowerment", "Performance Culture", "Sustainability"
     * If AWS: "Enterprise Innovation", "Security First", "Global Scalability", "Cost Efficiency", "Developer Empowerment"
     * If Airbnb: "Belonging Anywhere", "Host Stories", "Unique Experiences", "Community Connection", "Travel Dreams"

3. CREATE STRATEGIC CAMPAIGN THEMES:
   - theme_name: Catchy name (2-3 words)
   - focus: What this theme focuses on
   - key_message: Core message
   - visual_tone: How it should look visually
   - allocation_percent: Distribution (divide 100 among themes)

═══════════════════════════════════════════════════════════════════════════
RESPONSE FORMAT (JSON ONLY - NO MARKDOWN):
═══════════════════════════════════════════════════════════════════════════
{{
    "industry": "Their industry",
    "company_size": "Startup|Small|Mid-market|Enterprise|Unknown",
    "business_model": "B2B|B2C|B2B2C|Hybrid|Unknown",
    "target_audience": "Who they serve",
    "main_services": ["Service 1", "Service 2", "Service 3"],
    "brand_positioning": "How they position themselves",
    "unique_value": "What makes them unique",
    "brand_values": ["Value 1", "Value 2", "Value 3"],
    "data_source": "gemini",
    "campaign_themes": [
        {{
            "theme_name": "Theme Name",
            "focus": "What this theme focuses on",
            "key_message": "Core message for this theme",
            "visual_tone": "Descriptive visual style",
            "allocation_percent": 20
        }}
    ]
}}

CRITICAL: Themes must be SPECIFIC to this company. All percentages must sum to 100. JSON only.
═══════════════════════════════════════════════════════════════════════════"""

    _fallback = {
        "industry": "Unknown",
        "company_size": "Unknown",
        "business_model": "B2C",
        "target_audience": "General consumers",
        "main_services": [company_description],
        "brand_positioning": company_description,
        "unique_value": company_description,
        "brand_values": ["Quality", "Innovation", "Customer Focus"],
        "data_source": "fallback",
        "campaign_themes": [
            {
                "theme_name": company_name,
                "focus": "Brand awareness",
                "key_message": company_description,
                "visual_tone": "Professional and engaging",
                "allocation_percent": 100
            }
        ]
    }

    try:
        response = await gemini_client.aio.models.generate_content(
            model=gemini_model,
            contents=prompt
        )

        response_text = extract_gemini_text(response, "company analysis")
        log_gemini_usage(response, "[COMPANY] ")

        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(0)

        analysis = json.loads(response_text)
        analysis['data_source'] = 'gemini'

        if 'campaign_themes' not in analysis or not analysis['campaign_themes']:
            raise ValueError("No campaign themes in response")

        # Normalize allocation percentages
        total_percent = sum(t.get('allocation_percent', 20) for t in analysis['campaign_themes'])
        if total_percent != 100 and total_percent > 0:
            factor = 100 / total_percent
            for theme in analysis['campaign_themes']:
                theme['allocation_percent'] = int(theme.get('allocation_percent', 20) * factor)

        logger.info(f"[OK] Company analysis complete — {len(analysis['campaign_themes'])} themes")
        return analysis

    except json.JSONDecodeError as e:
        logger.error(f"[COMPANY] Failed to parse JSON: {e}")
        return _fallback

    except Exception as e:
        logger.error(f"[COMPANY] Analysis failed: {e}")
        logger.error(traceback.format_exc())
        return _fallback