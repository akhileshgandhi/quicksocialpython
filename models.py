from pydantic import BaseModel
from enum import Enum
from typing import Optional, Dict, List, Any
from datetime import datetime


# ===============================================================================
# TEXT MODEL CONSTANT (campaign.py used "gemini-2.0-flash-exp" for text calls)
# ===============================================================================
CAMPAIGN_TEXT_MODEL = "gemini-2.5-flash-lite"


# ===============================================================================
# CAMPAIGN ENUMS
# ===============================================================================

class CampaignGoal(str, Enum):
    """Campaign objectives/goals"""
    brand_awareness = "Brand awareness"
    lead_generation = "Lead generation"
    sales_conversion = "Sales & conversion"
    engagement = "Engagement"
    customer_retention = "Customer retention"


class ContentType(str, Enum):
    """Content type categories"""
    educational = "Educational"
    promotional = "Promotional"
    entertainment = "Entertainment"
    inspirational = "Inspirational"
    announcement = "Announcement"


class ContentStrategy(str, Enum):
    """Content strategy for multi-platform campaigns"""
    same_content = "same_content"  # Same post design for all platforms (resized)
    platform_specific = "platform_specific"  # Unique design per platform


# ===============================================================================
# SMART MODE ENUMS
# ===============================================================================

class PostingGoal(str, Enum):
    """Smart Mode - Posting Goals (What the user wants to achieve)"""
    promotional = "Promotional"  # Product/service promotion, offers, discounts
    engagement = "Engagement"  # Likes, comments, shares, community building
    announcement = "Announcement"  # New launch, updates, news
    brand_awareness = "Brand Awareness"  # Building brand recognition
    festival_event = "Festival/Event"  # Festival wishes, event promotions, celebrations


class ContentGenerationMode(str, Enum):
    """Smart Mode - How content should be generated"""
    single_post = "Single Post"  # One post with one caption
    ab_variations = "A/B Variations"  # 3 caption variations for the same image
    multi_slide = "Multi-Slide"  # Carousel with multiple slides


class MediaType(str, Enum):
    """Smart Mode - Type of media to generate"""
    single_image = "Single Image"  # One image
    image_carousel = "Image Carousel"  # 2-4 images for carousel


# ===============================================================================
# CAMPAIGN PLATFORM SPECS
# ===============================================================================

# Unified image dimensions for all platforms — no platform-specific sizing
IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350
IMAGE_ASPECT_RATIO = "4:5"
IMAGE_GEMINI_ASPECT = "3:4"

CAMPAIGN_PLATFORM_SPECS = {
    "instagram": {
        "name": "Instagram",
        "tone": "casual, trendy, emoji-friendly, visually engaging",
        "hashtag_count": 10,
        "caption_style": "short, punchy, engaging with emojis"
    },
    "facebook": {
        "name": "Facebook",
        "tone": "friendly, conversational, shareable, community-focused",
        "hashtag_count": 5,
        "caption_style": "medium length, storytelling, engaging"
    },
    "linkedin": {
        "name": "LinkedIn",
        "tone": "professional, thought-leadership, insightful, business-focused",
        "hashtag_count": 3,
        "caption_style": "longer, value-driven, expertise showcase"
    },
    "twitter": {
        "name": "Twitter/X",
        "tone": "concise, witty, attention-grabbing, trending",
        "hashtag_count": 3,
        "caption_style": "very short, impactful, conversation-starter"
    },
    "youtube": {
        "name": "YouTube",
        "tone": "descriptive, click-worthy, thumbnail-optimized",
        "hashtag_count": 5,
        "caption_style": "descriptive, keyword-rich, SEO-friendly"
    }
}


# ===============================================================================
# CAMPAIGN PYDANTIC MODELS
# ===============================================================================

class Feature(BaseModel):
    """Feature/Benefit with title and description"""
    title: str
    description: Optional[str] = None


class RequiredSkill(BaseModel):
    """Required skill with name and level"""
    skill_name: str
    level: Optional[str] = None


class CampaignProduct(BaseModel):
    """Product details for campaign with allocation percentage"""
    product_name: str
    description: Optional[str] = None
    price: Optional[str] = None
    pricing: Optional[str] = None
    sku: Optional[str] = None
    duration: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    features: Optional[List[Feature]] = None
    benefits: Optional[List[Feature]] = None
    required_skills: Optional[List[RequiredSkill]] = None
    image_url: Optional[str] = None
    post_percentage: Optional[float] = 50.0  # Percentage weightage for campaign distribution


class CampaignService(BaseModel):
    """Service details for campaign with allocation percentage"""
    service_name: str
    description: Optional[str] = None
    price: Optional[str] = None
    pricing: Optional[str] = None
    sku: Optional[str] = None
    duration: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    tags: Optional[List[str]] = None
    features: Optional[List[Feature]] = None
    benefits: Optional[List[Feature]] = None
    required_skills: Optional[List[RequiredSkill]] = None
    image_url: Optional[str] = None
    post_percentage: Optional[float] = 50.0  # Percentage weightage for campaign distribution


class GeneratedPost(BaseModel):
    """Single generated marketing post"""
    post_number: int
    platform: str
    item_type: str  # "product", "service", or "brand"
    item_name: str
    image_url: str
    image_preview: str
    layered: Optional[Dict[str, Any]] = None
    caption: str
    hashtags: List[str]
    aspect_ratio: str
    dimensions: str
    metadata: Dict[str, Any]


class CampaignResponse(BaseModel):
    """Campaign response with generated posts"""
    campaign_id: str
    campaign_name: str
    campaign_goal: str
    content_strategy: str
    campaign_folder: str  # Path to campaign folder where all images are stored
    total_posts_requested: int
    total_posts_generated: int
    generated_posts: List[GeneratedPost]
    schedule_info: Dict[str, Any]
    generation_summary: Dict[str, Any]


# ===============================================================================
# SMART MODE PYDANTIC MODELS
# ===============================================================================

class SmartPostCaption(BaseModel):
    """Single caption with hashtags for smart mode"""
    caption: str
    hashtags: List[str]
    variation_label: Optional[str] = None  # For A/B: "Version A", "Version B", etc.


class SmartPostImage(BaseModel):
    """Single generated image for smart mode"""
    image_url: str
    image_preview: str
    layered: Optional[Dict[str, Any]] = None
    local_path: str
    slide_number: Optional[int] = None  # For carousel: 1, 2, 3, 4


class SmartPostResponse(BaseModel):
    """Smart Mode - Generated post response"""
    post_id: str
    posting_goal: str
    content_mode: str
    media_type: str

    # Company Info (echoed back)
    company_name: str
    company_description: Optional[str]
    website: Optional[str]
    tagline: Optional[str]
    brand_voice: Optional[str]
    primary_color: str
    secondary_color: str
    accent_color: Optional[str]

    # Generated Content
    images: List[SmartPostImage]  # Single image or carousel (2-4 images)
    captions: List[SmartPostCaption]  # Single caption or A/B variations (3 captions)

    # Output folder
    output_folder: str

    # Metadata
    generated_at: str
    generation_summary: Dict[str, Any]



# ===============================================================================
# SMART SCRAPE PYDANTIC MODELS
# ===============================================================================

class TargetAudienceSegment(BaseModel):
    """Target audience segment details"""
    segment_name: str
    demographics: Optional[str] = None  # Age, gender, location, income
    psychographics: Optional[str] = None  # Interests, values, lifestyle


class ProductFeature(BaseModel):
    """Product feature with title and description"""
    title: str
    description: Optional[str] = None


class ScrapedProduct(BaseModel):
    """Scraped product information"""
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    price: Optional[str] = None
    url: Optional[str] = None
    tags: Optional[List[str]] = None
    features: Optional[List[ProductFeature]] = None
    image_urls: Optional[List[str]] = None


class ServiceBenefit(BaseModel):
    """Service benefit"""
    title: str
    description: Optional[str] = None


class ServiceSkill(BaseModel):
    """Required skill for service"""
    skill_name: str
    level: Optional[str] = None  # Beginner, Intermediate, Advanced, Expert


class ScrapedService(BaseModel):
    """Scraped service information"""
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    pricing: Optional[str] = None
    url: Optional[str] = None
    duration: Optional[str] = None
    tags: Optional[List[str]] = None
    benefits: Optional[List[ServiceBenefit]] = None
    skills: Optional[List[ServiceSkill]] = None
    image_urls: Optional[List[str]] = None
    video_urls: Optional[List[str]] = None


class ContentAsset(BaseModel):
    """Content asset discovered on the website"""
    title: str
    asset_type: str  # case_study, testimonial, pdf, whitepaper, brochure,
                     # blog_post, portfolio_item, gallery_image, video, infographic
    url: Optional[str] = None
    download_url: Optional[str] = None  # Direct file download (PDF, DOCX, etc.)
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    file_type: Optional[str] = None  # pdf, docx, mp4, etc.


class BrandIdentity(BaseModel):
    """Complete brand identity information"""
    name: str
    about: Optional[str] = None  # 2-3 line description
    country: Optional[str] = None  # ISO code (US, IN, UK, etc.)
    industry: Optional[str] = None  # Business sector (e.g., "Technology & Software")
    tagline: Optional[str] = None
    brand_voice: Optional[str] = None  # Communication style
    brand_tone: Optional[str] = None  # Emotion type (friendly, professional, luxurious)
    tone_attributes: Optional[List[str]] = None  # e.g., ["Professional", "Friendly", "Witty"]
    writing_style: Optional[str] = None  # e.g., "Short, punchy sentences with active voice"
    brand_story: Optional[str] = None
    brand_values: Optional[List[str]] = None
    key_selling_points: Optional[List[str]] = None
    competitor_diff: Optional[str] = None  # What makes them different
    target_audience: Optional[List[TargetAudienceSegment]] = None
    preferred_words: Optional[List[str]] = None
    content_guidelines: Optional[str] = None
    content_themes: Optional[List[str]] = None


class VisualBranding(BaseModel):
    """Visual branding elements.

    Frontend contract: ``primary_color``, ``secondary_color``, and ``accent_color``
    are single hex strings (``#RRGGBB``) from the HSL brand palette
    (``resolve_brand_palette`` in the agentic pipeline). See
    ``scraper_agents/VISUAL_BRANDING_ROLLBACK.md`` for list-based rollback.
    """
    primary_color: Optional[str] = None    # Brand primary, hex #RRGGBB
    secondary_color: Optional[str] = None   # Brand secondary, hex #RRGGBB
    accent_color: Optional[str] = None    # Brand accent, hex #RRGGBB
    headline_font: Optional[str] = None    # Primary heading font family (e.g., "Poppins")
    body_font: Optional[str] = None        # Body text font family (e.g., "Inter")
    headline_text_color: Optional[str] = None  # Hex code for heading text color
    google_fonts_url: Optional[str] = None # Full Google Fonts URL for embedding
    logo_url: Optional[str] = None         # Original source URL the logo was downloaded from
    logo_local_path: Optional[str] = None  # Local filesystem path


class SeoSocial(BaseModel):
    """SEO and social media information"""
    keywords: Optional[List[str]] = None  # 7-10 keywords
    hashtags: Optional[List[str]] = None  # 7-10 hashtags
    things_to_avoid: Optional[List[str]] = None


class SocialLinks(BaseModel):
    """Social media profile links"""
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    twitter: Optional[str] = None  # Also covers X (twitter.com or x.com)
    linkedin: Optional[str] = None
    youtube: Optional[str] = None
    tiktok: Optional[str] = None
    pinterest: Optional[str] = None
    github: Optional[str] = None
    other: Optional[List[str]] = None  # Any other social links found


class ContactInfo(BaseModel):
    """Contact information extracted from website"""
    emails: Optional[List[str]] = None
    phones: Optional[List[str]] = None
    addresses: Optional[List[str]] = None
    contact_page_url: Optional[str] = None


class SmartScrapeResponse(BaseModel):
    """Complete response from smart website scraping"""
    scrape_id: str
    website_url: str
    scrape_status: str  # "success", "partial", "fallback_used"
    data_source: str  # "website", "gemini_knowledge", "hybrid"

    # Brand Identity
    brand_identity: BrandIdentity

    # Visual Branding
    visual_branding: VisualBranding

    # SEO & Social
    seo_social: SeoSocial

    # Social Media Links
    social_links: Optional[SocialLinks] = None

    # Contact Information
    contact_info: Optional[ContactInfo] = None

    # Products & Services
    products: List[ScrapedProduct]
    services: List[ScrapedService]

    # Content Assets
    content_assets: Optional[List[ContentAsset]] = None

    # Metadata
    scraped_at: str
    scrape_summary: Dict[str, Any]
    # Optional: color extraction pipeline audit (sources, rules, candidates)
    color_audit: Optional[Dict[str, Any]] = None


# ===============================================================================
# MARKETING POST PYDANTIC MODELS
# ===============================================================================

class MarketingPostRequest(BaseModel):
    # Core Company Information
    company_name: str
    company_profile: str
    website: str
    logo: Optional[str] = None

    # Brand Identity
    industry: Optional[str] = None
    primary_brand_colors: Optional[str] = None
    secondary_brand_colors: Optional[str] = None

    # Brand Voice & Tone
    brand_voice: Optional[str] = None
    tone_attributes: Optional[str] = None
    writing_style: Optional[str] = None

    # Location & Messaging
    country: Optional[str] = None
    tagline: Optional[str] = None
    keywords: Optional[str] = None
    hashtags: Optional[str] = None

    # Marketing Content
    prompt: str


class CompleteImageResponse(BaseModel):
    """Production-grade response with permanent URL + all metadata"""
    image_url: str  # Permanent URL to saved image
    image_preview: str  # Base64 data URL for instant preview
    layered: Optional[Dict[str, Any]] = None
    caption: str
    hashtags: List[str]
    metadata: Dict[str, Any]
    safety_check: Dict[str, Any]



# ===============================================================================
# PROMPT ENHANCER MODELS
# ===============================================================================

class PromptOption(BaseModel):
    """Single visual scene option generated from user's rough idea"""
    title: str                # Short label, e.g. "Golden Hour Café Scene"
    scene_description: str    # Detailed visual prompt ready for image generation
    mood: str                 # Lighting/atmosphere, e.g. "Warm, inviting, cozy"
    style: str                # Photography approach, e.g. "Lifestyle photography, shallow DOF"


class PromptEnhancerResponse(BaseModel):
    """Response from /enhance-prompt — visual scene options"""
    original_prompt: str
    post_objective: Optional[str] = None
    platforms: Optional[List[str]] = None
    options: List[PromptOption]
 


# ===============================================================================
# REGENERATE IMAGE MODELS
# ===============================================================================
 
class RegenerateImageResponse(BaseModel):
    """Response from /regenerate-image — edited version of an existing image"""
    image_url: str                                        # /images/regenerated/...
    image_preview: str                                    # Base64 data URL
    original_image_url: Optional[str] = None              # Source image reference
    modification_prompt: str                              # Edit instruction applied
    caption: Optional[str] = None                         # AI caption (if requested)
    hashtags: Optional[List[str]] = None
    metadata: Dict[str, Any]
    original_metadata: Optional[Dict[str, Any]] = None    # From source .json sidecar