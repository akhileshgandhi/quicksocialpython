"""
Integration Test for Agent 02: CrawlAgent

This test verifies Agent 02's core functionality end-to-end:
- Input from Agent 01 (seo_project_context)
- Website crawling and inventory generation
- State persistence
- Output validation
- Data flow to downstream agents (Agent 03)

Run with:
    pytest tests/integration/test_agent02_integration.py -v
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from seo_agents.agents.crawl import CrawlAgent
from seo_agents.state import SEOState, save_seo_state, load_seo_state
from seo_agents.validators.schemas.site_inventory import SiteInventorySchema


# ================= SAMPLE DATA =================

SAMPLE_PROJECT_CONTEXTS = {
    "simple_site": {
        "website_url": "https://simple-example.com",
        "crawl_depth": 2,
        "max_pages": 10,
    },
    "complex_site": {
        "website_url": "https://complex-ecommerce.com",
        "crawl_depth": 3,
        "max_pages": 50,
    },
}

# Mock crawl response structure
MOCK_CRAWL_RESPONSE = {
    "total_pages": 5,
    "crawl_depth_reached": 2,
    "pages": [
        {
            "url": "https://simple-example.com",
            "status_code": 200,
            "title": "Simple Example Home",
            "meta_description": "Welcome to our simple site",
            "h1": "Simple Example",
            "word_count": 500,
            "response_time_ms": 150,
            "internal_links": ["/about", "/products", "/contact"],
            "external_links": [],
        },
        {
            "url": "https://simple-example.com/about",
            "status_code": 200,
            "title": "About Us",
            "meta_description": "Learn about us",
            "h1": "About Simple Example",
            "word_count": 300,
            "response_time_ms": 120,
            "internal_links": ["/"],
            "external_links": [],
        },
        {
            "url": "https://simple-example.com/products",
            "status_code": 200,
            "title": "Our Products",
            "meta_description": "View our products",
            "h1": "Products",
            "word_count": 800,
            "response_time_ms": 180,
            "internal_links": ["/", "/products/category-a"],
            "external_links": [],
        },
        {
            "url": "https://simple-example.com/contact",
            "status_code": 200,
            "title": "Contact Us",
            "meta_description": "Get in touch",
            "h1": "Contact",
            "word_count": 200,
            "response_time_ms": 100,
            "internal_links": ["/"],
            "external_links": [],
        },
        {
            "url": "https://simple-example.com/products/category-a",
            "status_code": 404,
            "title": None,
            "meta_description": None,
            "h1": None,
            "word_count": 0,
            "response_time_ms": 50,
            "internal_links": ["/products"],
            "external_links": [],
        },
    ],
    "crawl_errors": [
        {"url": "https://simple-example.com/missing-page", "error": "404 Not Found"}
    ],
}


# ================= MOCK GEMINI CLIENT =================

class MockGeminiClient:
    """Mock Gemini client for integration testing."""
    
    def __init__(self):
        self.call_count = 0
        self.last_prompt = None
        self._responses: Dict[str, str] = {}
        self._default_response = json.dumps(MOCK_CRAWL_RESPONSE)
        self.models = self  # Add .models attribute for new API
    
    def set_response_for_url(self, url: str, response: Dict[str, Any]) -> None:
        """Set a specific response for a URL."""
        self._responses[url] = json.dumps(response)
    
    def generate_content(self, model: str = None, contents: str = None, **kwargs) -> Any:
        self.call_count += 1
        self.last_prompt = contents if contents else ""
        
        # Extract URL from prompt to return appropriate response
        response_text = self._default_response
        contents_str = contents or ""
        for url, resp in self._responses.items():
            if url in contents_str:
                response_text = resp
                break
        
        class Response:
            def __init__(self, text):
                self.text = text
        
        return Response(response_text)
    
    async def generate_content_async(self, model: str, contents: str) -> Any:
        # Delegate to sync version for compatibility
        return self.generate_content(model, contents)


# ================= TEST FIXTURES =================

@pytest.fixture
def mock_gemini():
    """Create a fresh mock Gemini client."""
    return MockGeminiClient()


@pytest.fixture
def test_storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory."""
    storage = tmp_path / "seo_test_storage"
    storage.mkdir(exist_ok=True)
    return storage


@pytest.fixture
def state_with_project_context(test_storage_dir: Path) -> SEOState:
    """Create a sample SEOState with Agent 01 output (project context)."""
    project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
    
    state = SEOState(
        project_id="integration_test_002",
        brand_id="test_brand_002",
        website_url=project_data["website_url"],
        seo_project_context={
            "business_name": "Simple Example Inc",
            "website_url": project_data["website_url"],
            "industry": "Technology",
            "target_audience": ["Developers"],
            "primary_goals": ["Increase traffic"],
            "geographic_focus": "Global",
            "key_products_services": ["Software"],
        },
        config={
            "crawl_depth": project_data["crawl_depth"],
            "max_pages": project_data["max_pages"],
        },
        completed_agents=["agent_01_intake"],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    
    # Save initial state
    save_seo_state(state, test_storage_dir)
    
    return state


# ================= INTEGRATION TESTS =================

class TestAgent02Integration:
    """Integration tests for Agent 02: CrawlAgent."""
    
    @pytest.mark.asyncio
    async def test_full_crawl_flow(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Integration Test 1: Full crawl flow
        
        Steps:
        1. Create SEOState with Agent 01 output (seo_project_context)
        2. Run CrawlAgent
        3. Verify output structure
        4. Verify state persistence
        5. Verify data ready for downstream agents
        """
        # Arrange
        project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
        mock_gemini.set_response_for_url(
            project_data["website_url"],
            MOCK_CRAWL_RESPONSE
        )
        
        state = SEOState(
            project_id="test_crawl_flow",
            brand_id="brand_001",
            website_url=project_data["website_url"],
            seo_project_context={
                "website_url": project_data["website_url"],
                "business_name": "Simple Example",
            },
            config={
                "crawl_depth": project_data["crawl_depth"],
                "max_pages": project_data["max_pages"],
            },
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert - Output structure
        assert state.site_inventory is not None, "site_inventory should be set"
        assert state.status == "intelligence", "Status should be 'intelligence'"
        
        # Assert - Output content
        inventory = state.site_inventory
        assert inventory["total_pages"] > 0
        assert "pages" in inventory
        assert len(inventory["pages"]) > 0
        
        # Assert - Schema validation
        validated = SiteInventorySchema(**inventory)
        assert validated.total_pages > 0
        
        print(f"\n[OK] Integration Test 1 PASSED: Full crawl flow")
        print(f"  Total pages: {validated.total_pages}")
        print(f"  Crawl depth: {validated.crawl_depth_reached}")
        print(f"  Pages found: {len(validated.pages)}")
    
    @pytest.mark.asyncio
    async def test_crawl_respects_config(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Integration Test 2: Crawl respects configuration
        
        Tests that crawl_depth and max_pages from config are used.
        """
        # Arrange
        project_data = SAMPLE_PROJECT_CONTEXTS["complex_site"]
        
        state = SEOState(
            project_id="test_crawl_config",
            website_url=project_data["website_url"],
            seo_project_context={"website_url": project_data["website_url"]},
            config={
                "crawl_depth": project_data["crawl_depth"],
                "max_pages": project_data["max_pages"],
            },
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.site_inventory is not None
        inventory = state.site_inventory
        
        # The prompt should have included the crawl_depth and max_pages
        assert mock_gemini.last_prompt is not None
        assert str(project_data["crawl_depth"]) in mock_gemini.last_prompt
        assert str(project_data["max_pages"]) in mock_gemini.last_prompt
        
        print(f"\n[OK] Integration Test 2 PASSED: Config respected")
    
    @pytest.mark.asyncio
    async def test_state_persistence(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Integration Test 3: State persistence after agent execution
        
        Verifies that state can be saved and reloaded correctly.
        """
        # Arrange
        project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
        
        state = SEOState(
            project_id="test_crawl_persistence",
            website_url=project_data["website_url"],
            seo_project_context={"website_url": project_data["website_url"]},
            config={"crawl_depth": 2},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Act - Execute agent
        await agent.execute(state)
        
        # Save state
        save_seo_state(state, test_storage_dir)
        
        # Reload state
        reloaded_state = load_seo_state("test_crawl_persistence", test_storage_dir)
        
        # Assert
        assert reloaded_state.site_inventory is not None
        assert reloaded_state.status == "intelligence"
        assert reloaded_state.website_url == state.website_url
        
        print(f"\n[OK] Integration Test 3 PASSED: State persistence")
    
    @pytest.mark.asyncio
    async def test_data_ready_for_agent_03(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Integration Test 4: Data ready for Agent 03 (Technical Audit)
        
        Verifies that Agent 02 produces data that Agent 03 expects.
        """
        # Arrange
        project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
        
        state = SEOState(
            project_id="test_agent03_ready",
            website_url=project_data["website_url"],
            seo_project_context={"website_url": project_data["website_url"]},
            config={"crawl_depth": 2},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert - Data needed by Agent 03
        inventory = state.site_inventory
        
        # Agent 03 needs: pages list with metadata
        assert "pages" in inventory
        assert len(inventory["pages"]) > 0
        
        # Check page structure for Agent 03
        first_page = inventory["pages"][0]
        # Handle both dict and Pydantic model
        if hasattr(first_page, 'model_dump'):
            first_page_dict = first_page.model_dump()
            assert "url" in first_page_dict
            assert "status_code" in first_page_dict
            assert "title" in first_page_dict
        else:
            assert "url" in first_page
            assert "status_code" in first_page
            assert "title" in first_page
        
        print(f"\n[OK] Integration Test 4 PASSED: Data ready for Agent 03")
        print(f"  Page count: {len(inventory['pages'])}")
    
    @pytest.mark.asyncio
    async def test_crawl_with_errors(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Integration Test 5: Crawl handles page errors
        
        Verifies that crawl errors are captured in the output.
        """
        # Arrange - Response with errors
        response_with_errors = {
            "total_pages": 1,
            "crawl_depth_reached": 1,
            "pages": [
                {
                    "url": "https://error-test.com",
                    "status_code": 200,
                    "title": "Home",
                    "meta_description": "Test",
                    "h1": "Home",
                    "word_count": 100,
                    "response_time_ms": 50,
                    "internal_links": [],
                    "external_links": [],
                }
            ],
            "crawl_errors": [
                {"url": "https://error-test.com/broken", "error": "404 Not Found"},
                {"url": "https://error-test.com/timeout", "error": "Connection timeout"},
            ]
        }
        mock_gemini.set_response_for_url("https://error-test.com", response_with_errors)
        
        state = SEOState(
            project_id="test_crawl_errors",
            website_url="https://error-test.com",
            seo_project_context={"website_url": "https://error-test.com"},
            config={"crawl_depth": 2},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.site_inventory is not None
        assert "crawl_errors" in state.site_inventory
        assert len(state.site_inventory["crawl_errors"]) > 0
        
        print(f"\n[OK] Integration Test 5 PASSED: Crawl with errors")


class TestAgent02ErrorHandling:
    """Integration tests for error handling."""
    
    @pytest.mark.asyncio
    async def test_missing_seo_project_context(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """Test that missing seo_project_context is properly handled."""
        state = SEOState(
            project_id="test_missing_context",
            website_url="https://test.com",
            seo_project_context=None,  # Missing context
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Errors are now caught and logged gracefully - verify execution completes
        await agent.execute(state)
        
        # Verify error was logged - no API calls made due to validation failure
        assert mock_gemini.call_count == 0
        
        print(f"\n[OK] Error Test PASSED: Missing seo_project_context handled gracefully")
    
    @pytest.mark.asyncio
    async def test_missing_website_url(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """Test that missing website_url is properly handled."""
        state = SEOState(
            project_id="test_missing_url",
            website_url="",
            seo_project_context={"business_name": "Test"},  # Has context but no website_url
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        
        # Errors are now caught and logged gracefully - verify execution completes
        await agent.execute(state)
        
        # Verify error was logged - no API calls made due to validation failure
        assert mock_gemini.call_count == 0
        
        print(f"\n[OK] Error Test PASSED: Missing website_url handled gracefully")


class TestAgent02DataValidation:
    """Integration tests for data validation."""
    
    @pytest.mark.asyncio
    async def test_output_schema_validation(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """Test that output passes Pydantic schema validation."""
        project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
        
        state = SEOState(
            project_id="test_schema",
            website_url=project_data["website_url"],
            seo_project_context={"website_url": project_data["website_url"]},
            config={"crawl_depth": 2},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        await agent.execute(state)
        
        # Validate with Pydantic schema - should not raise
        schema = SiteInventorySchema(**state.site_inventory)
        
        # Verify all required fields are present
        assert schema.total_pages > 0
        assert schema.crawl_depth_reached >= 0
        assert len(schema.pages) > 0
        assert schema.crawl_errors is not None
        
        print(f"\n[OK] Schema Validation Test PASSED")
    
    @pytest.mark.asyncio
    async def test_page_record_validation(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """Test that individual page records are valid."""
        project_data = SAMPLE_PROJECT_CONTEXTS["simple_site"]
        
        state = SEOState(
            project_id="test_page_records",
            website_url=project_data["website_url"],
            seo_project_context={"website_url": project_data["website_url"]},
            config={"crawl_depth": 2},
            completed_agents=["agent_01_intake"],
        )
        
        agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        await agent.execute(state)
        
        # Check first page structure
        schema = SiteInventorySchema(**state.site_inventory)
        first_page = schema.pages[0]
        
        # Required fields for each page
        assert first_page.url is not None
        assert first_page.status_code > 0
        assert first_page.word_count >= 0
        assert first_page.response_time_ms >= 0
        assert first_page.internal_links is not None
        assert first_page.external_links is not None
        
        print(f"\n[OK] Page Record Validation Test PASSED")


# ================= TEST RUNNER =================

def run_all_tests():
    """Run all integration tests programmatically."""
    import subprocess
    import sys
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        capture_output=False,
    )
    
    return result.returncode


if __name__ == "__main__":
    # Run tests when executed directly
    exit_code = run_all_tests()
    exit(exit_code)