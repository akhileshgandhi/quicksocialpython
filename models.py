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

CAMPAIGN_PLATFORM_SPECS = {
    "instagram": {
        "name": "Instagram",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "gemini_aspect": "3:4",
        "tone": "casual, trendy, emoji-friendly, visually engaging",
        "hashtag_count": 10,
        "caption_style": "short, punchy, engaging with emojis"
    },
    "facebook": {
        "name": "Facebook",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "gemini_aspect": "3:4",
        "tone": "friendly, conversational, shareable, community-focused",
        "hashtag_count": 5,
        "caption_style": "medium length, storytelling, engaging"
    },
    "linkedin": {
        "name": "LinkedIn",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "gemini_aspect": "3:4",
        "tone": "professional, thought-leadership, insightful, business-focused",
        "hashtag_count": 3,
        "caption_style": "longer, value-driven, expertise showcase"
    },
    "twitter": {
        "name": "Twitter/X",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "gemini_aspect": "3:4",
        "tone": "concise, witty, attention-grabbing, trending",
        "hashtag_count": 3,
        "caption_style": "very short, impactful, conversation-starter"
    },
    "youtube": {
        "name": "YouTube",
        "aspect_ratio": "4:5",
        "width": 1080,
        "height": 1350,
        "gemini_aspect": "3:4",
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
    brand_colors: Optional[str]

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
    """Visual branding elements"""
    primary_color: Optional[List[str]] = None  # Brand colors: all logo colors + dominant website color
    secondary_color: Optional[str] = None  # Deprecated — always None
    headline_font: Optional[str] = None  # Primary heading font family (e.g., "Poppins")
    body_font: Optional[str] = None  # Body text font family (e.g., "Inter")
    headline_text_color: Optional[str] = None  # Hex code for heading text color
    google_fonts_url: Optional[str] = None  # Full Google Fonts URL for embedding
    logo_url: Optional[str] = None  # Original source URL the logo was downloaded from
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
    """Single creative direction generated from user's rough idea"""
    title: str                # Campaign concept name, e.g. "The Permission to Pause"
    scene_description: str    # Complete visual brief — scene, composition, light, color, style, and emotional payoff
 
 
class PromptEnhancerResponse(BaseModel):
    """Response from /enhance-prompt — 3 visual scene options"""
    original_prompt: str
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


# ===============================================================================
# SEO PROJECT PYDANTIC MODELS (Phase 2.1)
# ===============================================================================

class SEOProjectStatus(str, Enum):
    """SEO project pipeline status"""
    discovery = "discovery"
    intelligence = "intelligence"
    strategy = "strategy"
    execution = "execution"
    monitoring = "monitoring"
    paused = "paused"
    archived = "archived"


class ApprovalGate(BaseModel):
    """Approval gate for pipeline pauses"""
    required: bool = False
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class SEOProjectConfig(BaseModel):
    """SEO project configuration"""
    crawl_depth: int = 3
    target_geography: str = "Global"
    auto_approve: bool = False


class SEOProject(BaseModel):
    """SEO Project API model for request/response validation"""
    project_id: str
    brand_id: str
    status: SEOProjectStatus = SEOProjectStatus.DISCOVERY
    current_layer: int = 1
    completed_agents: List[str] = []
    approval_gates: Dict[str, ApprovalGate] = {
        "gate1_technical": ApprovalGate(),
        "gate2_strategy": ApprovalGate(),
        "gate3_content": ApprovalGate(),
        "gate4_reoptimization": ApprovalGate(),
    }
    config: SEOProjectConfig = SEOProjectConfig()
    created_at: datetime
    updated_at: datetime


# ===============================================================================
# SEO DATA OBJECT MODEL (Phase 2.1.2)
# ===============================================================================

class SEODataType(str, Enum):
    """SEO data object types"""
    seo_project_context = "seo_project_context"
    site_inventory = "site_inventory"
    technical_audit_report = "technical_audit_report"
    competitor_matrix = "competitor_matrix"
    keyword_universe = "keyword_universe"
    keyword_clusters = "keyword_clusters"
    page_keyword_map = "page_keyword_map"
    content_gap_report = "content_gap_report"
    seo_priority_backlog = "seo_priority_backlog"
    page_optimization_briefs = "page_optimization_briefs"
    content_briefs = "content_briefs"
    content_drafts = "content_drafts"
    internal_link_graph = "internal_link_graph"
    schema_map = "schema_map"
    performance_dashboard = "performance_dashboard"
    reoptimization_queue = "reoptimization_queue"


class SEODataObject(BaseModel):
    """SEO Data Object API model"""
    project_id: str
    agent_id: str
    data_type: SEODataType
    version: int = 1
    data: Dict[str, Any]
    created_by: Optional[str] = None
    created_at: datetime


# ===============================================================================
# SEO JOB MODEL (Phase 2.1.3)
# ===============================================================================

class SEOJobStatus(str, Enum):
    """SEO job execution status"""
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SEOJobError(BaseModel):
    """SEO job error details"""
    message: str
    stack: Optional[str] = None


class SEOJob(BaseModel):
    """SEO Job API model"""
    job_id: str
    project_id: str
    agent_id: str
    status: SEOJobStatus = SEOJobStatus.PENDING
    progress: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[SEOJobError] = None
    input_data_types: List[str] = []
    output_data_type: Optional[str] = None
    execution_time_ms: Optional[int] = None
    triggered_by: Optional[str] = None
    created_at: datetime


# ===============================================================================
# SEO API REQUEST/RESPONSE MODELS (Phase 4.3)
# ===============================================================================

class SEOProjectCreate(BaseModel):
    """Request model for creating SEO project"""
    brand_id: str
    website_url: str
    config: Optional[SEOProjectConfig] = None
    intake_data: Optional[Dict[str, Any]] = None


class GateApprovalRequest(BaseModel):
    """Request model for gate approval"""
    approved_by: str


class SEOProjectResponse(BaseModel):
    """Response model for SEO project"""
    project_id: str
    brand_id: str
    website_url: Optional[str] = None
    status: SEOProjectStatus
    current_layer: int
    completed_agents: List[str]
    completed_agents_count: int
    approval_gates: Dict[str, ApprovalGate]
    config: SEOProjectConfig
    created_at: datetime
    updated_at: datetime


class SEOStatusResponse(BaseModel):
    """Response model for status endpoint"""
    project_id: str
    status: str
    current_layer: int
    completed_agents: List[str]
    errors: List[str]
    approval_gates: Dict[str, Any]
    total_time_seconds: float


class PipelineStartResponse(BaseModel):
    """Response model for pipeline start"""
    status: str
    project_id: str
    message: str


class GateApprovalResponse(BaseModel):
    """Response model for gate approval"""
    status: str
    gate: str
    approved_at: str
 