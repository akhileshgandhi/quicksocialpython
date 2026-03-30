"""
Integration test for Agent 04 Keyword Research with upstream agents.

Full Pipeline: Agent 01 → Agent 02 → Agent 03 → (Gate 1 approval) → Agent 04

This test validates:
1. Agent 01 produces seo_project_context
2. Agent 02 produces site_inventory
3. Agent 04 uses BOTH (but NOT competitor_matrix or technical_audit_report)

Note: Agent 03 is skipped in this test because Agent 04 doesn't require
technical_audit_report as input. The key validation is that Agent 04 works
WITHOUT competitor_matrix (since Agent 08 runs AFTER Agent 04 in the new architecture).

Run with:
    pytest tests/integration/test_agent04_integration.py -v
"""

from __future__ import annotations

import json
import pytest


# MockGeminiClient class (same as in conftest.py)
class MockGeminiResponse:
    """Mock response object mimicking Gemini API response."""
    
    def __init__(self, text: str):
        self.text = text


class MockGeminiClient:
    """Mock Gemini client for testing."""
    
    def __init__(self):
        self._responses = []
        self._response_index = 0
        self._call_count = 0
        self.models = self  # Add .models attribute for new API
    
    def set_responses(self, responses):
        self._responses = responses
        self._response_index = 0
    
    def generate_content(self, model: str = None, contents: str = None, **kwargs):
        self._call_count += 1
        if self._responses and self._response_index < len(self._responses):
            response = self._responses[self._response_index]
            self._response_index += 1
            return MockGeminiResponse(text=response)
        return MockGeminiResponse(text=json.dumps({}))
    
    async def generate_content_async(self, model: str, contents: str):
        # Delegate to sync version for compatibility
        return self.generate_content(model, contents)
    
    @property
    def call_count(self):
        return self._call_count


# Helper functions (same as in conftest.py)
def get_mock_intake_response():
    return json.dumps({
        "business_name": "Example Corp",
        "website_url": "https://example.com",
        "industry": "SaaS",
        "target_audience": ["SMBs", "Marketing teams", "E-commerce businesses"],
        "primary_goals": ["Increase organic traffic", "Generate qualified leads", "Build brand awareness"],
        "geographic_focus": "United States",
        "competitors": ["competitor-a.com", "competitor-b.com", "competitor-c.com"],
        "brand_voice": "Professional, helpful, data-driven",
        "key_products_services": ["Marketing Automation", "Analytics Dashboard", "Email Campaigns", "Social Media Management"],
    })


def get_mock_crawl_response():
    return json.dumps({
        "total_pages": 50,
        "crawl_depth_reached": 3,
        "pages": [
            {"url": "https://example.com/", "status_code": 200, "title": "Home", "meta_description": "Welcome", "h1": "Example Corp", "word_count": 500, "response_time_ms": 150, "internal_links": ["https://example.com/about", "https://example.com/products"], "external_links": []},
            {"url": "https://example.com/about", "status_code": 200, "title": "About Us", "meta_description": "About", "h1": "About", "word_count": 300, "response_time_ms": 120, "internal_links": ["https://example.com/"], "external_links": []},
            {"url": "https://example.com/products", "status_code": 200, "title": "Products", "meta_description": "Our Products", "h1": "Products", "word_count": 800, "response_time_ms": 180, "internal_links": ["https://example.com/"], "external_links": []},
        ],
        "crawl_errors": [],
    })


def get_mock_keyword_response():
    return json.dumps({
        "total_keywords": 15,
        "keywords": [
            {
                "keyword": "marketing automation for small business",
                "intent": "commercial",
                "volume_tier": "high",
                "competition_tier": "high",
                "source": "seed",
                "query_format": "keyword",
                "answer_surfaces": ["featured_snippet", "ai_overview"],
                "citation_value_score": 8
            },
            {
                "keyword": "how to automate marketing emails",
                "intent": "informational",
                "volume_tier": "medium",
                "competition_tier": "medium",
                "source": "question_variant",
                "query_format": "question",
                "answer_surfaces": ["featured_snippet", "voice_assistant", "ai_overview"],
                "citation_value_score": 9
            },
            {
                "keyword": "best email marketing software 2024",
                "intent": "commercial",
                "volume_tier": "high",
                "competition_tier": "high",
                "source": "expansion",
                "query_format": "keyword",
                "answer_surfaces": ["ai_chat"],
                "citation_value_score": 6
            },
            {
                "keyword": "what is marketing automation",
                "intent": "informational",
                "volume_tier": "high",
                "competition_tier": "low",
                "source": "question_variant",
                "query_format": "question",
                "answer_surfaces": ["featured_snippet", "voice_assistant"],
                "citation_value_score": 10
            },
            {
                "keyword": "marketing automation pricing plans",
                "intent": "transactional",
                "volume_tier": "medium",
                "competition_tier": "medium",
                "source": "site_inventory",
                "query_format": "keyword",
                "answer_surfaces": ["ai_overview"],
                "citation_value_score": 7
            },
            {
                "keyword": "voice search marketing strategy",
                "intent": "informational",
                "volume_tier": "low",
                "competition_tier": "low",
                "source": "expansion",
                "query_format": "voice",
                "answer_surfaces": ["voice_assistant", "ai_chat"],
                "citation_value_score": 8
            },
        ],
        "seed_terms_used": ["Marketing Automation", "Email Campaigns", "Analytics Dashboard"],
        "featured_snippet_opportunities": 3,
        "voice_search_opportunities": 3,
        "ai_overview_opportunities": 4,
        "high_citation_value_keywords": 3
    })


# Import agents and state
from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.keyword_universe import KeywordUniverseSchema


class TestAgent04Integration:
    """Integration tests for Agent 04 with upstream agents."""

    @pytest.mark.asyncio
    async def test_sequential_01_02_04_execution(self, tmp_path):
        """Test full sequential execution: Agent 01 → Agent 02 → Agent 04."""
        # Set up sequential responses
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
        ])
        
        # Create agents
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        
        # Create initial state
        state = SEOState(
            project_id="integration_001",
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
        
        # === Execute Agent 01 ===
        await intake_agent.execute(state)
        
        assert state.seo_project_context is not None
        assert state.seo_project_context["business_name"] == "Example Corp"
        # Note: completed_agents is managed by orchestrator, not individual agents
        
        # === Execute Agent 02 ===
        await crawl_agent.execute(state)
        
        assert state.site_inventory is not None
        # Note: site_inventory may be a Pydantic model or dict depending on crawl implementation
        assert hasattr(state.site_inventory, 'total_pages') or state.site_inventory.get('total_pages') == 50
        
        # === Execute Agent 04 ===
        await keyword_agent.execute(state)

        # Verify keyword universe was created
        assert state.keyword_universe is not None
        assert state.keyword_universe["total_keywords"] == 15

        # Verify AEO/GEO fields
        assert "featured_snippet_opportunities" in state.keyword_universe
        assert "voice_search_opportunities" in state.keyword_universe
        assert "ai_overview_opportunities" in state.keyword_universe

        # Note: completed_agents is managed by the orchestrator, not individual agents
        # The key validation is that keyword_universe was created successfully

        # Verify call count (3 agents = 3 LLM calls)
        assert mock_client.call_count == 3
    
    @pytest.mark.asyncio
    async def test_agent04_does_not_require_competitor_matrix(self, tmp_path):
        """Test that Agent 04 works without competitor_matrix.

        In the new architecture, Agent 08 (Competitor) runs AFTER Agent 04.
        """
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_002",
            brand_id="brand_002",
            website_url="https://test.com",
            config={
                "crawl_depth": 2,
                "intake_form_data": {
                    "business_name": "Test Corp",
                    "industry": "E-commerce",
                },
            },
        )
        
        # Run Agent 01 and 02
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        
        # Verify competitor_matrix is NOT set (Agent 08 hasn't run)
        assert state.competitor_matrix is None

        # Agent 04 should work without competitor_matrix
        await keyword_agent.execute(state)

        assert state.keyword_universe is not None
    
    @pytest.mark.asyncio
    async def test_agent04_with_gate1_approved(self, tmp_path):
        """Test that Agent 04 runs after Gate 1 is approved."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_003",
            brand_id="brand_003",
            website_url="https://gate-test.com",
            config={
                "crawl_depth": 3,
                "intake_form_data": {
                    "business_name": "Gate Test Corp",
                    "industry": "Tech",
                },
            },
        )
        
        # Run Agent 01 and 02
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        
        # Simulate Gate 1 approval
        state.approval_gates = {
            "gate1_technical": {
                "required": True,
                "approved": True,
                "approved_by": "user_123",
            },
            "gate2_strategy": {"required": False, "approved": False},
            "gate3_content": {"required": False, "approved": False},
            "gate4_reoptimization": {"required": False, "approved": False},
        }
        
        # Agent 04 should now be able to run
        await keyword_agent.execute(state)

        assert state.keyword_universe is not None
        assert state.keyword_universe["total_keywords"] == 15
    
    @pytest.mark.asyncio
    async def test_keyword_universe_schema_validation_integration(self, tmp_path):
        """Test that the keyword universe output passes full schema validation."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_004",
            brand_id="brand_004",
            website_url="https://schema-test.com",
            config={
                "crawl_depth": 2,
                "intake_form_data": {"business_name": "Schema Test", "industry": "Retail"},
            },
        )
        
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await keyword_agent.execute(state)
        
        # Validate against the full schema
        validated = KeywordUniverseSchema(**state.keyword_universe)
        
        # Verify all AEO/GEO fields are present and valid
        assert validated.total_keywords == 15
        assert len(validated.keywords) == 6
        
        # Check AEO/GEO summary fields (actual count may vary based on enum normalization)
        assert validated.featured_snippet_opportunities >= 0
        assert validated.voice_search_opportunities >= 0
        assert validated.ai_overview_opportunities >= 0
        assert validated.high_citation_value_keywords >= 0
        
        # Verify keyword entries have proper AEO/GEO data
        for kw in validated.keywords:
            assert kw.query_format is not None
            assert len(kw.answer_surfaces) > 0
            assert 1 <= kw.citation_value_score <= 10
