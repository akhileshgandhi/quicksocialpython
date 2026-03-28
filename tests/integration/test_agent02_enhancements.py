"""
Test Agent 02 Enhancements - Normalization and Edge Cases

This test specifically validates the enhancements made to Agent 02:
1. None → [] normalization for list fields
2. String → list conversion
3. Default values for missing optional fields
4. Schema validation

Run with:
    pytest tests/integration/test_agent02_enhancements.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from seo_agents.agents.crawl import CrawlAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.site_inventory import (
    SiteInventorySchema,
    PageRecord,
    ImageInfo,
    OpenGraphTags,
    SitemapInfo,
    RobotsTxtInfo,
)


# ================= EDGE CASE MOCK RESPONSES =================

def get_mock_response_with_none_values() -> str:
    """Mock response with None values that should be normalized to []"""
    return json.dumps({
        "total_pages": 2,
        "crawl_depth_reached": 1,
        "pages": [
            {
                "url": "https://example.com/",
                "status_code": 200,
                "title": "Home",
                "meta_description": None,  # None should stay None (optional field)
                "h1": "Home",
                "h2_tags": None,  # None → []
                "h3_tags": None,  # None → []
                "schema_types": None,  # None → []
                "internal_links": None,  # None → []
                "external_links": None,  # None → []
                "word_count": 100,
                "response_time_ms": 100,
            },
        ],
        "crawl_errors": [],
        # Missing optional fields - should get defaults
        # "sitemap" missing
        # "robots_txt" missing
        # "duplicate_titles" missing
        # "duplicate_meta_descriptions" missing
        # "thin_content_pages" missing
    })


def get_mock_response_with_string_values() -> str:
    """Mock response with string values that should be converted to lists"""
    return json.dumps({
        "total_pages": 1,
        "crawl_depth_reached": 1,
        "pages": [
            {
                "url": "https://example.com/",
                "status_code": 200,
                "title": "Home",
                "h2_tags": "Single H2 Tag",  # String → ["Single H2 Tag"]
                "h3_tags": "Another H3 Tag",
                "schema_types": "Organization",
                "internal_links": "https://example.com/about",  # String → ["url"]
                "external_links": "https://external.com",
                "word_count": 100,
                "response_time_ms": 100,
            },
        ],
        "crawl_errors": [],
    })


def get_mock_response_with_nested_objects() -> str:
    """Mock response with nested dicts that should become Pydantic objects"""
    return json.dumps({
        "total_pages": 1,
        "crawl_depth_reached": 1,
        "pages": [
            {
                "url": "https://example.com/",
                "status_code": 200,
                "title": "Home",
                "h2_tags": [],
                "h3_tags": [],
                "schema_types": [],
                "internal_links": [],
                "external_links": [],
                "word_count": 100,
                "response_time_ms": 100,
                "og_tags": {  # Should become OpenGraphTags object
                    "og_title": "OG Title",
                    "og_description": "OG Description",
                    "og_image": "https://example.com/og.jpg",
                },
                "images": [  # Should become list of ImageInfo objects
                    {"src": "https://example.com/img.jpg", "alt": "Image", "is_optimized": True}
                ],
            },
        ],
        "crawl_errors": [],
        "sitemap": {  # Should become SitemapInfo object
            "found": True,
            "url": "https://example.com/sitemap.xml",
            "pages_count": 10,
        },
        "robots_txt": {  # Should become RobotsTxtInfo object
            "found": True,
            "url": "https://example.com/robots.txt",
            "allows_crawl": True,
        },
    })


# ================= MOCK GEMINI CLIENT =================

class MockGeminiClient:
    """Mock Gemini client for testing edge cases."""
    
    def __init__(self, response: str):
        self._response = response
        self._call_count = 0
    
    async def generate_content_async(self, model: str, contents: str) -> Any:
        self._call_count += 1
        
        class Response:
            def __init__(self, text):
                self.text = text
        
        return Response(self._response)


# ================= TEST FIXTURES =================

@pytest.fixture
def test_storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory."""
    storage = tmp_path / "seo_enhancement_test"
    storage.mkdir(exist_ok=True)
    return storage


# ================= ENHANCEMENT TESTS =================

class TestAgent02Enhancements:
    """Tests for Agent 02 specific enhancements."""
    
    @pytest.mark.asyncio
    async def test_normalization_none_to_list(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 1: None values should be normalized to empty lists
        
        This tests the _normalize_page_record() method which converts:
        - h2_tags: None → []
        - h3_tags: None → []
        - schema_types: None → []
        - internal_links: None → []
        - external_links: None → []
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_response_with_none_values())
        state = SEOState(
            project_id="enhancement_test_001",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            config={"crawl_depth": 1, "max_pages": 10},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.site_inventory is not None, "site_inventory should be set"
        
        # Get pages - handle both dict and Pydantic
        pages = state.site_inventory.pages if hasattr(state.site_inventory, 'pages') else state.site_inventory["pages"]
        first_page = pages[0]
        
        # Get page dict or object
        page_dict = first_page.model_dump() if hasattr(first_page, 'model_dump') else first_page
        
        # Verify None → [] normalization
        assert page_dict["h2_tags"] == [], f"h2_tags should be [], got {page_dict['h2_tags']}"
        assert page_dict["h3_tags"] == [], f"h3_tags should be [], got {page_dict['h3_tags']}"
        assert page_dict["schema_types"] == [], f"schema_types should be [], got {page_dict['schema_types']}"
        assert page_dict["internal_links"] == [], f"internal_links should be [], got {page_dict['internal_links']}"
        assert page_dict["external_links"] == [], f"external_links should be [], got {page_dict['external_links']}"
        
        print("\n✓ Enhancement Test 1 PASSED: None → [] normalization works!")
    
    @pytest.mark.asyncio
    async def test_normalization_string_to_list(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 2: String values should be converted to lists
        
        This tests that single string values are converted:
        - "Single H2 Tag" → ["Single H2 Tag"]
        - "https://example.com/about" → ["https://example.com/about"]
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_response_with_string_values())
        state = SEOState(
            project_id="enhancement_test_002",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            config={"crawl_depth": 1, "max_pages": 10},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.site_inventory is not None
        
        pages = state.site_inventory.pages if hasattr(state.site_inventory, 'pages') else state.site_inventory["pages"]
        first_page = pages[0]
        page_dict = first_page.model_dump() if hasattr(first_page, 'model_dump') else first_page
        
        # Verify string → list conversion
        assert page_dict["h2_tags"] == ["Single H2 Tag"], f"h2_tags should be ['Single H2 Tag'], got {page_dict['h2_tags']}"
        assert page_dict["h3_tags"] == ["Another H3 Tag"], f"h3_tags should be ['Another H3 Tag'], got {page_dict['h3_tags']}"
        assert page_dict["schema_types"] == ["Organization"], f"schema_types should be ['Organization'], got {page_dict['schema_types']}"
        assert page_dict["internal_links"] == ["https://example.com/about"], f"internal_links should be ['https://example.com/about'], got {page_dict['internal_links']}"
        assert page_dict["external_links"] == ["https://external.com"], f"external_links should be ['https://external.com'], got {page_dict['external_links']}"
        
        print("\n✓ Enhancement Test 2 PASSED: String → list conversion works!")
    
    @pytest.mark.asyncio
    async def test_normalization_nested_objects(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 3: Nested dicts should become Pydantic objects
        
        This tests that:
        - og_tags dict → OpenGraphTags object
        - images dicts → ImageInfo objects
        - sitemap dict → SitemapInfo object
        - robots_txt dict → RobotsTxtInfo object
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_response_with_nested_objects())
        state = SEOState(
            project_id="enhancement_test_003",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            config={"crawl_depth": 1, "max_pages": 10},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert - Check nested objects are Pydantic models
        inventory = state.site_inventory
        
        # Check sitemap is SitemapInfo
        sitemap = inventory.sitemap if hasattr(inventory, 'sitemap') else inventory.get("sitemap")
        assert sitemap is not None, "sitemap should be set"
        assert isinstance(sitemap, SitemapInfo), f"sitemap should be SitemapInfo, got {type(sitemap)}"
        assert sitemap.found == True
        assert sitemap.pages_count == 10
        
        # Check robots_txt is RobotsTxtInfo
        robots = inventory.robots_txt if hasattr(inventory, 'robots_txt') else inventory.get("robots_txt")
        assert robots is not None, "robots_txt should be set"
        assert isinstance(robots, RobotsTxtInfo), f"robots_txt should be RobotsTxtInfo, got {type(robots)}"
        assert robots.allows_crawl == True
        
        # Check pages
        pages = inventory.pages if hasattr(inventory, 'pages') else inventory.get("pages")
        first_page = pages[0]
        
        # Check og_tags is OpenGraphTags
        og_tags = first_page.og_tags if hasattr(first_page, 'og_tags') else first_page.get("og_tags")
        assert og_tags is not None
        assert isinstance(og_tags, OpenGraphTags), f"og_tags should be OpenGraphTags, got {type(og_tags)}"
        assert og_tags.og_title == "OG Title"
        
        # Check images are ImageInfo objects
        images = first_page.images if hasattr(first_page, 'images') else first_page.get("images")
        assert images is not None
        assert len(images) == 1
        assert isinstance(images[0], ImageInfo), f"images[0] should be ImageInfo, got {type(images[0])}"
        assert images[0].src == "https://example.com/img.jpg"
        
        print("\n✓ Enhancement Test 3 PASSED: Nested objects → Pydantic models works!")
    
    @pytest.mark.asyncio
    async def test_default_values_for_missing_fields(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 4: Missing optional fields should get default values
        
        This tests that:
        - duplicate_titles defaults to []
        - duplicate_meta_descriptions defaults to []
        - thin_content_pages defaults to []
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_response_with_none_values())
        state = SEOState(
            project_id="enhancement_test_004",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            config={"crawl_depth": 1, "max_pages": 10},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert - Check default values (handle dict vs Pydantic)
        inventory = state.site_inventory
        
        # Use dict access since it might be a dict
        dup_titles = inventory.get("duplicate_titles") if isinstance(inventory, dict) else inventory.duplicate_titles
        dup_meta = inventory.get("duplicate_meta_descriptions") if isinstance(inventory, dict) else inventory.duplicate_meta_descriptions
        thin = inventory.get("thin_content_pages") if isinstance(inventory, dict) else inventory.thin_content_pages
        
        # These fields were missing in the mock response, should get defaults
        assert dup_titles == [], f"duplicate_titles should default to [], got {dup_titles}"
        assert dup_meta == [], f"duplicate_meta_descriptions should default to [], got {dup_meta}"
        assert thin == [], f"thin_content_pages should default to [], got {thin}"
        
        print("\n✓ Enhancement Test 4 PASSED: Default values for missing fields works!")
    
    @pytest.mark.asyncio
    async def test_schema_validation(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 5: Output should pass Pydantic schema validation
        
        This tests that the _validate_outputs() method works correctly.
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_response_with_nested_objects())
        state = SEOState(
            project_id="enhancement_test_005",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            config={"crawl_depth": 1, "max_pages": 10},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act - Execute should validate schema automatically
        await agent.execute(state)
        
        # Assert - If we get here, validation passed
        # Manually validate to confirm
        validated = SiteInventorySchema(**state.site_inventory)
        
        assert validated.total_pages == 1
        assert validated.crawl_depth_reached == 1
        assert len(validated.pages) == 1
        assert validated.sitemap is not None
        assert validated.robots_txt is not None
        
        print("\n✓ Enhancement Test 5 PASSED: Schema validation works!")


class TestAgent02InputValidation:
    """Tests for Agent 02 input validation."""
    
    @pytest.mark.asyncio
    async def test_missing_seo_project_context(
        self,
        test_storage_dir: Path,
    ):
        """Test that missing seo_project_context raises ValueError."""
        # Arrange
        mock_client = MockGeminiClient("{}")
        state = SEOState(
            project_id="validation_test_001",
            brand_id="brand_001",
            website_url="https://example.com",
            # NO seo_project_context - should fail
            config={"crawl_depth": 1},
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act & Assert
        with pytest.raises(ValueError, match="seo_project_context required"):
            await agent.execute(state)
        
        print("\n✓ Input Validation Test PASSED: Missing seo_project_context caught!")
    
    @pytest.mark.asyncio
    async def test_missing_website_url(
        self,
        test_storage_dir: Path,
    ):
        """Test that website_url fallback works (uses state.website_url as backup)."""
        # Note: The code actually has a fallback to state.website_url, so this won't fail
        # Test demonstrates the fallback behavior works correctly
        
        # Arrange
        mock_response = json.dumps({
            "total_pages": 1,
            "crawl_depth_reached": 1,
            "pages": [],
            "crawl_errors": [],
        })
        mock_client = MockGeminiClient(mock_response)
        
        state = SEOState(
            project_id="validation_test_002",
            brand_id="brand_001",
            website_url="https://example.com",  # Fallback URL
            seo_project_context={"business_name": "Test"},  # No website_url in context
            config={"crawl_depth": 1},
        )
        
        agent = CrawlAgent(mock_client, "test-model", test_storage_dir)
        
        # Act - Should NOT raise because fallback to state.website_url works
        await agent.execute(state)
        
        # Assert - Should work because fallback URL is used
        assert state.site_inventory is not None
        
        print("\n✓ Input Validation Test PASSED: website_url fallback works!")
