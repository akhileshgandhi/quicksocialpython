"""
CrawlAgent (Agent 02) — performs async breadth-first crawl of the website.

This agent performs a comprehensive SEO audit of a website by crawling pages
and collecting detailed metadata for on-page SEO analysis.

Input:
    state.seo_project_context (from Agent 01) - website_url
    
Output:
    SiteInventorySchema - Complete site inventory with SEO metadata

Functional Logic:
    1. Extract the root URL from seo_project_context
    2. Build comprehensive crawl prompt with SEO requirements
    3. Call LLM to perform crawl and build inventory
    4. Normalize response to match Pydantic schema
    5. Store validated inventory and update status

SEO Data Collected:
    - Page URLs, status codes, titles, meta descriptions
    - Heading tags (H1, H2, H3)
    - Canonical URLs, robots directives
    - Open Graph meta tags
    - Schema.org JSON-LD markup
    - Image optimization data
    - Internal/external links
    - Sitemap.xml and robots.txt detection
    - Duplicate and thin content detection
    - Response time metrics

Gate Logic: None — pipeline continues immediately

Usage:
    agent = CrawlAgent(gemini_client, model, storage_dir)
    await agent.execute(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Dict, Type

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState
from seo_agents.utils import normalize_list_field, normalize_dict_value

if TYPE_CHECKING:
    from seo_agents.validators.schemas.site_inventory import SiteInventorySchema


class CrawlAgent(SEOBaseAgent):
    """Agent responsible for crawling websites and building SEO site inventory."""
    
    agent_name: ClassVar[str] = "agent_02_crawl"
    triggers_approval_gate: ClassVar[bool] = False
    response_schema: ClassVar[Type[Any]] = None  # Set at call time

    def _validate_inputs(self, state: SEOState) -> None:
        """Validate required input fields exist before running the agent.
        
        Args:
            state: SEOState with seo_project_context containing website_url
            
        Raises:
            ValueError: If seo_project_context is missing or website_url is not provided
        """
        if not state.seo_project_context:
            raise ValueError("seo_project_context required (run Agent 01 first)")
        
        website_url = state.seo_project_context.get("website_url", state.website_url)
        if not website_url:
            raise ValueError("website_url is required in seo_project_context")

    def _validate_outputs(self, state: SEOState) -> None:
        """Validate output was properly set by the agent.
        
        Args:
            state: SEOState that should contain site_inventory
            
        Raises:
            ValueError: If site_inventory is not set or fails schema validation
        """
        from seo_agents.validators.schemas.site_inventory import SiteInventorySchema
        
        if not state.site_inventory:
            raise ValueError("site_inventory was not set by CrawlAgent")
        
        SiteInventorySchema(**state.site_inventory)

    def _normalize_page_record(self, page: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a single page record to match the schema.
        
        Args:
            page: Raw page dictionary from LLM response
            
        Returns:
            Normalized page dictionary ready for Pydantic validation
        """
        normalized = page.copy()
        
        # Handle nested OpenGraphTags
        if "og_tags" in normalized and isinstance(normalized.get("og_tags"), dict):
            from seo_agents.validators.schemas.site_inventory import OpenGraphTags
            og_data = normalized["og_tags"]
            normalized["og_tags"] = OpenGraphTags(**og_data) if og_data else None
        
        # Handle nested ImageInfo objects
        if "images" in normalized and isinstance(normalized.get("images"), list):
            from seo_agents.validators.schemas.site_inventory import ImageInfo
            images = []
            for img in normalized["images"]:
                if isinstance(img, dict):
                    images.append(ImageInfo(**img))
            normalized["images"] = images
        
        # Ensure list fields are lists, not None or strings
        list_fields = ["h2_tags", "h3_tags", "schema_types", "internal_links", "external_links"]
        for field in list_fields:
            normalized[field] = normalize_list_field(normalized.get(field))
        
        # AEO/GEO Enhancement: Set defaults for new fields if missing
        from seo_agents.validators.schemas.site_inventory import StructuredDataQuality, FeaturedSnippetEligibility
        
        normalized.setdefault("has_faq_schema", False)
        normalized.setdefault("has_speakable_markup", False)
        normalized.setdefault("has_question_content", False)
        normalized.setdefault("structured_data_quality", StructuredDataQuality.NONE)
        normalized.setdefault("featured_snippet_eligibility", FeaturedSnippetEligibility.UNKNOWN)
        
        return normalized

    def _normalize_inventory(self, inventory: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize the complete inventory to match the schema.
        
        Args:
            inventory: Raw inventory dictionary from LLM response
            
        Returns:
            Normalized inventory dictionary ready for Pydantic validation
        """
        normalized = inventory.copy()
        
        # Normalize page records
        if "pages" in normalized and isinstance(normalized.get("pages"), list):
            from seo_agents.validators.schemas.site_inventory import PageRecord
            pages = []
            for page in normalized["pages"]:
                if isinstance(page, dict):
                    page = self._normalize_page_record(page)
                    pages.append(PageRecord(**page))
            normalized["pages"] = pages
        
        # Normalize sitemap
        if "sitemap" in normalized and isinstance(normalized.get("sitemap"), dict):
            from seo_agents.validators.schemas.site_inventory import SitemapInfo
            normalized["sitemap"] = SitemapInfo(**normalized["sitemap"])
        
        # Normalize robots_txt
        if "robots_txt" in normalized and isinstance(normalized.get("robots_txt"), dict):
            from seo_agents.validators.schemas.site_inventory import RobotsTxtInfo
            normalized["robots_txt"] = RobotsTxtInfo(**normalized["robots_txt"])
        
        # Ensure default values for optional fields
        normalized.setdefault("duplicate_titles", [])
        normalized.setdefault("duplicate_meta_descriptions", [])
        normalized.setdefault("thin_content_pages", [])
        
        # AEO/GEO Enhancement: Set defaults for summary fields if missing
        normalized.setdefault("pages_with_faq_schema", 0)
        normalized.setdefault("pages_with_speakable_markup", 0)
        normalized.setdefault("pages_with_question_content", 0)
        normalized.setdefault("pages_with_excellent_structured_data", 0)
        normalized.setdefault("pages_eligible_for_featured_snippets", 0)
        
        # Normalize AEO fields that might come as strings from LLM
        from seo_agents.validators.schemas.site_inventory import StructuredDataQuality, FeaturedSnippetEligibility
        
        sdq = normalized.get("structured_data_quality")
        if isinstance(sdq, str):
            try:
                normalized["structured_data_quality"] = StructuredDataQuality(sdq)
            except ValueError:
                normalized["structured_data_quality"] = StructuredDataQuality.NONE
        
        fse = normalized.get("featured_snippet_eligibility")
        if isinstance(fse, str):
            try:
                normalized["featured_snippet_eligibility"] = FeaturedSnippetEligibility(fse)
            except ValueError:
                normalized["featured_snippet_eligibility"] = FeaturedSnippetEligibility.UNKNOWN
        
        return normalized

    def __all__(self) -> list[str]:
        return ["CrawlAgent", self.agent_name]

    async def run(self, state: SEOState) -> None:
        """Execute the crawl agent to build site inventory.
        
        Args:
            state: SEOState with seo_project_context containing website_url
            
        Returns:
            None - Results are stored in state.site_inventory
        """
        from seo_agents.prompts.crawl import build_crawl_prompt
        from seo_agents.validators.schemas.site_inventory import SiteInventorySchema

        self.log(f"Starting site crawl for: {state.website_url}")

        website_url = state.seo_project_context.get("website_url", state.website_url)
        crawl_depth = state.config.get("crawl_depth", 3)
        max_pages = state.config.get("max_pages", 500)

        prompt = build_crawl_prompt(website_url, crawl_depth, max_pages)

        # Execute crawl via LLM
        raw_inventory = await self._call_gemini(prompt=prompt)
        
        # Normalize and validate response
        inventory = self._normalize_inventory(raw_inventory)

        state.site_inventory = inventory
        state.status = "intelligence"
        
        # Log summary metrics
        self.log(f"Crawl complete. Total pages: {inventory.get('total_pages', 0)}")
        self.log(f"Pages with H1: {inventory.get('pages_with_h1', 0)}")
        self.log(f"Pages with Schema: {inventory.get('pages_with_schema', 0)}")
