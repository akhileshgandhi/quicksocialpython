"""
Unit tests for Agent 01: IntakeAgent

Tests follow the standard testing protocol from the implementation plan:
1. Happy path - valid inputs produce correct output
2. Missing input - ValueError raised for missing required fields
3. LLM failure - retry logic recovers from transient errors
4. Timeout - agent handles timeout gracefully
5. Output validation failure - malformed output is caught
"""

from __future__ import annotations

import asyncio
import json
import pytest

from seo_agents.agents.intake import IntakeAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.seo_project_context import SEOProjectContextSchema

from tests.seo_agents.conftest import (
    MockGeminiClient,
    get_mock_intake_response,
)


class TestIntakeAgentHappyPath:
    """Test 1: Happy path - valid inputs produce correct output."""
    
    @pytest.mark.asyncio
    async def test_basic_intake_with_form_data(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test intake agent with pre-populated form data."""
        # Arrange
        mock_gemini_client.set_response(get_mock_intake_response())
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_001",
            brand_id="brand_001",
            website_url="https://example.com",
            config={
                "crawl_depth": 3,
                "target_geography": "United States",
                "intake_form_data": {
                    "business_name": "Example Corp",
                    "industry": "SaaS",
                    "target_audience": ["SMBs"],
                    "primary_goals": ["Increase traffic"],
                },
            },
        )
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.seo_project_context is not None
        assert state.seo_project_context["business_name"] == "Example Corp"
        assert state.seo_project_context["website_url"] == "https://example.com"
        assert state.seo_project_context["industry"] == "SaaS"
        assert isinstance(state.seo_project_context["target_audience"], list)
        assert isinstance(state.seo_project_context["primary_goals"], list)
        assert state.status == "intelligence"
        assert mock_gemini_client.call_count == 1
    
    @pytest.mark.asyncio
    async def test_intake_without_form_data(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test intake agent when no form data is provided (inference only)."""
        # Arrange
        mock_gemini_client.set_response(get_mock_intake_response())
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_002",
            brand_id="brand_002",
            website_url="https://acme.com",
            config={
                "crawl_depth": 3,
                "target_geography": "Global",
                # No intake_form_data - agent should still work
            },
        )
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.seo_project_context is not None
        assert "business_name" in state.seo_project_context
        assert "website_url" in state.seo_project_context
        assert state.status == "intelligence"
    
    @pytest.mark.asyncio
    async def test_output_matches_schema(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that output conforms to SEOProjectContextSchema."""
        # Arrange
        mock_gemini_client.set_response(get_mock_intake_response())
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_003",
            website_url="https://example.com",
        )
        
        # Act
        await agent.execute(state)
        
        # Assert - Should not raise
        schema = SEOProjectContextSchema(**state.seo_project_context)
        assert schema.business_name is not None
        assert schema.website_url == "https://example.com"


class TestIntakeAgentMissingInput:
    """Test 2: Missing input - ValueError raised for missing required fields."""
    
    @pytest.mark.asyncio
    async def test_missing_website_url(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that ValueError is raised when website_url is missing."""
        # Arrange
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_004", website_url="")
        
        # Act & Assert
        with pytest.raises(ValueError, match="website_url is required"):
            await agent.execute(state)
    
    @pytest.mark.asyncio
    async def test_invalid_website_url_format(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that ValueError is raised for invalid URL format."""
        # Arrange
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_005", website_url="not-a-valid-url")
        
        # Act & Assert
        with pytest.raises(ValueError, match="Invalid website_url format"):
            await agent.execute(state)
    
    @pytest.mark.asyncio
    async def test_missing_website_url_error_logged(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that missing website_url error is captured in state.errors."""
        # Arrange
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_006", website_url="")
        
        # Act
        await agent.execute(state)
        
        # Assert - Error should be in state.errors
        assert len(state.errors) > 0
        assert any("website_url" in err for err in state.errors)


class TestIntakeAgentLLMFailure:
    """Test 3: LLM failure - retry logic recovers from transient errors."""
    
    @pytest.mark.asyncio
    async def test_retry_on_transient_error(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that agent retries when LLM raises transient error."""
        # Arrange
        # First two calls fail, third succeeds
        mock_gemini_client.set_raise_on_call(Exception("Transient API error"))
        mock_gemini_client.set_response(get_mock_intake_response())
        
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_007", website_url="https://example.com")
        
        # Act - With tenacity retry (3 attempts), 2 failures should still succeed
        # Note: The retry logic is in _call_gemini, so we expect it to retry
        await agent.execute(state)
        
        # Assert - Should eventually succeed
        assert state.seo_project_context is not None
        # Note: Due to tenacity retry, call_count may be > 1
    
    @pytest.mark.asyncio
    async def test_all_retries_fail(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test behavior when all LLM calls fail."""
        # Arrange
        mock_gemini_client.set_raise_on_call(Exception("Persistent API error"))
        
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_008", website_url="https://example.com")
        
        # Act
        await agent.execute(state)
        
        # Assert - Error should be captured
        assert len(state.errors) > 0


class TestIntakeAgentTimeout:
    """Test 4: Timeout - agent handles timeout gracefully."""
    
    @pytest.mark.asyncio
    async def test_agent_timeout(
        self,
        tmp_storage_dir,
    ):
        """Test that agent handles timeout when LLM takes too long."""
        # Arrange - Create a slow mock client
        class SlowGeminiClient:
            async def generate_content_async(self, model, contents):
                await asyncio.sleep(35)  # Longer than default 30s budget
                return type('Response', (), {'text': '{"test": "data"}'})()
        
        slow_client = SlowGeminiClient()
        agent = IntakeAgent(slow_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_009", website_url="https://example.com")
        
        # Act
        await agent.execute(state)
        
        # Assert - Should have timeout error
        assert any("timed out" in err for err in state.errors)


class TestIntakeAgentOutputValidation:
    """Test 5: Output validation failure - malformed output is caught."""
    
    @pytest.mark.asyncio
    async def test_malformed_json_response(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that malformed JSON from LLM is handled."""
        # Arrange
        mock_gemini_client.set_response("This is not valid JSON at all!")
        
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_010", website_url="https://example.com")
        
        # Act
        await agent.execute(state)
        
        # Assert - Error should be captured
        assert len(state.errors) > 0
    
    @pytest.mark.asyncio
    async def test_incomplete_json_response(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that JSON missing required fields is caught by schema validation."""
        # Arrange - JSON missing required fields
        incomplete_response = json.dumps({
            "business_name": "Test",
            # Missing website_url, industry, etc.
        })
        mock_gemini_client.set_response(incomplete_response)
        
        agent = IntakeAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        state = SEOState(project_id="test_011", website_url="https://example.com")
        
        # Act
        await agent.execute(state)
        
        # Assert - Schema validation error should be captured
        assert len(state.errors) > 0


class TestIntakeAgentSchemaValidation:
    """Additional tests for schema validation."""
    
    def test_schema_validates_required_fields(self):
        """Test that SEOProjectContextSchema requires all required fields."""
        # Valid data should work
        valid_data = {
            "business_name": "Test",
            "website_url": "https://test.com",
            "industry": "Tech",
            "target_audience": ["B2B"],
            "primary_goals": ["Leads"],
            "geographic_focus": "US",
            "key_products_services": ["Product"],
        }
        schema = SEOProjectContextSchema(**valid_data)
        assert schema.business_name == "Test"
        
        # Missing required field should raise
        with pytest.raises(Exception):  # Pydantic ValidationError
            SEOProjectContextSchema(
                business_name="Test",
                # Missing other required fields
            )
    
    def test_schema_allows_optional_fields(self):
        """Test that optional fields can be None or omitted."""
        minimal_data = {
            "business_name": "Test",
            "website_url": "https://test.com",
            "industry": "Tech",
            "target_audience": ["B2B"],
            "primary_goals": ["Leads"],
            "geographic_focus": "US",
            "key_products_services": ["Product"],
        }
        
        # Without optional fields
        schema1 = SEOProjectContextSchema(**minimal_data)
        assert schema1.brand_voice is None
        
        # With optional fields
        schema2 = SEOProjectContextSchema(**minimal_data, brand_voice="Professional")
        assert schema2.brand_voice == "Professional"
