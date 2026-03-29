"""
Unit tests for Agent 04: KeywordResearchAgent

Tests follow the standard testing protocol from the implementation plan:
1. Happy path - valid inputs produce correct output with AEO/GEO fields
2. Missing input - ValueError raised for missing required fields
3. Output validation - malformed output is caught
4. Normalization - LLM responses with different formats are normalized correctly
"""

from __future__ import annotations

import json
import pytest

from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.keyword_universe import KeywordUniverseSchema

from tests.seo_agents.conftest import (
    MockGeminiClient,
    get_mock_keyword_response,
)


class TestKeywordResearchAgentHappyPath:
    """Test 1: Happy path - valid inputs produce correct output with AEO/GEO fields."""
    
    @pytest.mark.asyncio
    async def test_basic_keyword_research(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test keyword research agent with pre-populated context and inventory."""
        # Arrange
        mock_gemini_client.set_response(get_mock_keyword_response())
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_001",
            brand_id="brand_001",
            website_url="https://example.com",
            config={"crawl_depth": 3, "target_geography": "United States"},
        )
        
        # Set up required inputs (simulating Agent 01 and 02 completion)
        state.seo_project_context = {
            "business_name": "Example Corp",
            "industry": "SaaS",
            "target_audience": ["SMBs", "Marketing teams"],
            "primary_goals": ["Increase traffic", "Generate leads"],
            "geographic_focus": "United States",
            "key_products_services": ["Marketing Automation", "Analytics Dashboard"],
        }
        state.site_inventory = {
            "total_pages": 10,
            "pages": [
                {"url": "https://example.com/", "title": "Home", "h1": "Example Corp"},
                {"url": "https://example.com/products", "title": "Products", "h1": "Our Products"},
            ]
        }
        state.completed_agents = ["agent_01_intake", "agent_02_crawl"]
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.keyword_universe is not None
        assert state.keyword_universe["total_keywords"] == 15
        assert len(state.keyword_universe["keywords"]) == 6
        assert isinstance(state.keyword_universe["keywords"], list)
        
        # Verify AEO/GEO fields
        assert "featured_snippet_opportunities" in state.keyword_universe
        assert "voice_search_opportunities" in state.keyword_universe
        assert "ai_overview_opportunities" in state.keyword_universe
        assert "high_citation_value_keywords" in state.keyword_universe
        
        # Verify first keyword has all AEO/GEO fields
        first_kw = state.keyword_universe["keywords"][0]
        assert "query_format" in first_kw
        assert "answer_surfaces" in first_kw
        assert "citation_value_score" in first_kw
        
        assert mock_gemini_client.call_count == 1
    
    @pytest.mark.asyncio
    async def test_keyword_research_with_minimal_inputs(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test keyword research with minimal required fields."""
        # Arrange
        mock_gemini_client.set_response(get_mock_keyword_response())
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_002",
            brand_id="brand_002",
            website_url="https://minimal.com",
            config={"crawl_depth": 2},
        )
        
        # Set up minimal required inputs
        state.seo_project_context = {
            "industry": "E-commerce",
            "key_products_services": ["Online Store"],
        }
        state.site_inventory = {"pages": []}
        state.completed_agents = ["agent_01_intake", "agent_02_crawl"]
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.keyword_universe is not None
        assert "keywords" in state.keyword_universe


class TestKeywordResearchAgentInputValidation:
    """Test 2: Missing input - ValueError raised for missing required fields."""
    
    @pytest.mark.asyncio
    async def test_missing_seo_project_context(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that missing seo_project_context raises ValueError."""
        # Arrange
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_003",
            brand_id="brand_003",
            website_url="https://error.com",
        )
        # Only set site_inventory, not seo_project_context
        state.site_inventory = {"pages": []}
        
        # Act & Assert
        with pytest.raises(ValueError, match="seo_project_context required"):
            await agent.execute(state)
    
    @pytest.mark.asyncio
    async def test_missing_site_inventory(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that missing site_inventory raises ValueError."""
        # Arrange
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_004",
            brand_id="brand_004",
            website_url="https://error.com",
        )
        # Only set seo_project_context, not site_inventory
        state.seo_project_context = {"industry": "SaaS"}
        
        # Act & Assert
        with pytest.raises(ValueError, match="site_inventory required"):
            await agent.execute(state)


class TestKeywordResearchAgentNormalization:
    """Test 4: Normalization - LLM responses with different formats are normalized."""
    
    @pytest.mark.asyncio
    async def test_keyword_enum_normalization(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that LLM responses with various enum formats are normalized correctly."""
        # Arrange - response with mixed case and different formats
        mixed_response = json.dumps({
            "total_keywords": 2,
            "keywords": [
                {
                    "keyword": "test keyword",
                    "intent": "INFORMATIONAL",  # uppercase
                    "volume_tier": "High",  # Title case
                    "competition_tier": "medium",
                    "source": "seed",
                    "query_format": "Question",  # Title case
                    "answer_surfaces": ["FEATURED_SNIPPET", "voice_assistant"],  # mixed
                    "citation_value_score": "8",  # string
                },
                {
                    "keyword": "another keyword",
                    "intent": "commercial",
                    "volume_tier": "low",
                    "competition_tier": "HIGH",
                    "source": "expansion",
                    "query_format": "conversational",
                    "answer_surfaces": "ai_overview",  # string instead of list
                    "citation_value_score": 15,  # over max
                },
            ],
            "seed_terms_used": ["test"],
            "featured_snippet_opportunities": 1,
            "voice_search_opportunities": 1,
            "ai_overview_opportunities": 2,
            "high_citation_value_keywords": 1,
        })
        mock_gemini_client.set_response(mixed_response)
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_005",
            brand_id="brand_005",
            website_url="https://normalize.com",
            config={},
        )
        state.seo_project_context = {"industry": "SaaS", "key_products_services": ["Test"]}
        state.site_inventory = {"pages": []}
        
        # Act
        await agent.execute(state)
        
        # Assert - values should be normalized
        first_kw = state.keyword_universe["keywords"][0]
        
        # Check enum normalization
        assert first_kw["intent"] == "informational"  # lowercase
        assert first_kw["volume_tier"] == "high"  # lowercase
        assert first_kw["query_format"] == "question"  # lowercase
        
        # Check citation score bounds (15 should become 10)
        second_kw = state.keyword_universe["keywords"][1]
        assert second_kw["citation_value_score"] == 10  # capped at max
        
        # Check answer_surfaces normalization
        assert isinstance(first_kw["answer_surfaces"], list)
        assert "featured_snippet" in first_kw["answer_surfaces"]
        assert "voice_assistant" in first_kw["answer_surfaces"]
    
    @pytest.mark.asyncio
    async def test_missing_optional_fields_get_defaults(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that missing optional fields get default values."""
        # Arrange - minimal response
        minimal_response = json.dumps({
            "total_keywords": 1,
            "keywords": [
                {
                    "keyword": "basic keyword",
                    # Missing: intent, volume_tier, competition_tier, source
                    # Missing: query_format, answer_surfaces, citation_value_score
                }
            ],
            "seed_terms_used": [],
        })
        mock_gemini_client.set_response(minimal_response)
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_006",
            brand_id="brand_006",
            website_url="https://defaults.com",
            config={},
        )
        state.seo_project_context = {"industry": "SaaS", "key_products_services": ["Test"]}
        state.site_inventory = {"pages": []}
        
        # Act
        await agent.execute(state)
        
        # Assert - defaults should be applied
        first_kw = state.keyword_universe["keywords"][0]
        
        assert first_kw["intent"] == "informational"  # default
        assert first_kw["volume_tier"] == "medium"  # default
        assert first_kw["competition_tier"] == "medium"  # default
        assert first_kw["query_format"] == "keyword"  # default
        assert first_kw["citation_value_score"] == 5  # default
        
        # Answer surfaces should have at least one default
        assert len(first_kw["answer_surfaces"]) > 0


class TestKeywordResearchAgentOutputValidation:
    """Test 3: Output validation - malformed output is caught."""
    
    @pytest.mark.asyncio
    async def test_invalid_output_structure(
        self,
        mock_gemini_client: MockGeminiClient,
        tmp_storage_dir,
    ):
        """Test that invalid output structure raises validation error."""
        # Arrange - invalid response (missing required fields)
        invalid_response = json.dumps({
            "total_keywords": "not_an_integer",  # wrong type
            "keywords": "not_a_list",  # wrong type
        })
        mock_gemini_client.set_response(invalid_response)
        agent = KeywordResearchAgent(mock_gemini_client, "test-model", tmp_storage_dir)
        
        state = SEOState(
            project_id="test_007",
            brand_id="brand_007",
            website_url="https://invalid.com",
            config={},
        )
        state.seo_project_context = {"industry": "SaaS", "key_products_services": ["Test"]}
        state.site_inventory = {"pages": []}
        
        # Act & Assert - should raise validation error
        with pytest.raises(Exception):  # Pydantic validation error
            await agent.execute(state)
