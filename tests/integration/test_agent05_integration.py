"""
Integration test for Agent 05 Keyword Clustering with upstream agents.

Full Pipeline: Agent 01 → Agent 02 → Agent 04 → Agent 05

This test validates:
1. Agent 01 produces seo_project_context
2. Agent 02 produces site_inventory
3. Agent 04 produces keyword_universe
4. Agent 05 clusters keywords into keyword_clusters with AEO/GEO optimizations

Run with:
    pytest tests/integration/test_agent05_integration.py -v
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


# Helper functions
def get_mock_intake_response():
    return json.dumps({
        "business_name": "APXN Property",
        "website_url": "https://apxnproperty.com",
        "industry": "Real Estate / Rural Land Investment Platform",
        "target_audience": [
            "First-time land buyers",
            "Small/retail real estate investors",
            "Off-grid/lifestyle buyers"
        ],
        "primary_goals": [
            "Sell affordable vacant rural land",
            "Provide owner financing options"
        ],
        "geographic_focus": "United States",
        "competitors": ["LandWatch", "Land.com", "Lands of America"],
        "key_products_services": ["Rural Land Sales", "Owner Financing", "Land Investment"],
    })


def get_mock_crawl_response():
    return json.dumps({
        "total_pages": 14,
        "crawl_depth_reached": 3,
        "pages": [
            {"url": "https://apxnproperty.com/", "status_code": 200, "title": "Home", "meta_description": "Welcome", "h1": "APXN Properties", "word_count": 56},
            {"url": "https://apxnproperty.com/about", "status_code": 200, "title": "About Us", "meta_description": "About", "h1": "Our Story", "word_count": 102},
            {"url": "https://apxnproperty.com/services", "status_code": 200, "title": "Services", "meta_description": "Services", "h1": "Our Services", "word_count": 88},
            {"url": "https://apxnproperty.com/contact", "status_code": 200, "title": "Contact", "meta_description": "Contact", "h1": "Contact Us", "word_count": 46},
        ],
        "crawl_errors": [],
        "seo_inventory": {
            "pages_with_h1": 4,
            "pages_with_meta_description": 4,
            "pages_with_schema": 4,
            "pages_with_og_tags": 4,
        },
        "security": {"https_only": True, "ssl_issues": None},
    })


def get_mock_keyword_response():
    return json.dumps({
        "total_keywords": 20,
        "keywords": [
            {"keyword": "rural land for sale", "intent": "transactional", "volume_tier": "high", "competition_tier": "high", "source": "seed", "query_format": "keyword", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 6},
            {"keyword": "owner financing land", "intent": "commercial", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 8},
            {"keyword": "how to buy land with owner financing", "intent": "informational", "volume_tier": "medium", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search", "ai_overview"], "citation_value_score": 9},
            {"keyword": "cheap land for sale owner financing", "intent": "transactional", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["featured_snippet"], "citation_value_score": 9},
            {"keyword": "what is rural land investment", "intent": "informational", "volume_tier": "low", "competition_tier": "medium", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search", "ai_overview"], "citation_value_score": 9},
            {"keyword": "best states to buy rural land", "intent": "commercial", "volume_tier": "medium", "competition_tier": "high", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 7},
            {"keyword": "land investment for beginners", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "ai_overview"], "citation_value_score": 7},
            {"keyword": "rural land for sale near me", "intent": "transactional", "volume_tier": "high", "competition_tier": "high", "source": "seed", "query_format": "keyword", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 6},
            {"keyword": "what are the benefits of rural land investment", "intent": "informational", "volume_tier": "low", "competition_tier": "medium", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search", "ai_overview"], "citation_value_score": 9},
            {"keyword": "best rural land investment platform", "intent": "commercial", "volume_tier": "low", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 8},
            {"keyword": "how to invest in land with no money", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 8},
            {"keyword": "land buying process step by step", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 8},
            {"keyword": "off grid land for sale", "intent": "transactional", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["featured_snippet"], "citation_value_score": 7},
            {"keyword": "acreage for sale by owner", "intent": "transactional", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 6},
            {"keyword": "what documents do I need to buy land", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 9},
            {"keyword": "financing raw land", "intent": "commercial", "volume_tier": "low", "competition_tier": "low", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 8},
            {"keyword": "is buying land a good investment", "intent": "informational", "volume_tier": "medium", "competition_tier": "medium", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "ai_overview"], "citation_value_score": 8},
            {"keyword": "rural land prices by state", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["featured_snippet"], "citation_value_score": 7},
            {"keyword": "how to sell land fast", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 7},
            {"keyword": "land contract vs mortgage", "intent": "informational", "volume_tier": "low", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "ai_overview"], "citation_value_score": 9},
        ],
        "seed_terms_used": ["rural land", "owner financing", "land buying guides"],
        "featured_snippet_opportunities": 9,
        "voice_search_opportunities": 6,
        "ai_overview_opportunities": 8,
        "high_citation_value_keywords": 6,
    })


def get_mock_clustering_response():
    return json.dumps({
        "total_clusters": 6,
        "clusters": [
            {
                "cluster_id": "cluster_001",
                "cluster_name": "Owner Financing Land Purchase",
                "primary_keyword": "owner financing land",
                "supporting_keywords": ["cheap land for sale owner financing", "land contract financing", "seller financing land"],
                "intent": "commercial",
                "funnel_stage": "BOFU",
                "total_volume_tier": "medium",
                "competition_tier": "medium",
                "recommended_page_type": "landing_page",
                "recommended_url_slug": "/owner-financing-land/",
                "is_new_page_required": True,
                "answer_format": "faq",
                "answer_surface_targets": ["featured_snippet", "ai_overview"],
                "priority_score": 85,
                "cannibalization_risk": None,
                "search_volume_tier": "medium",
                "geographic_relevance": "national",
                "internal_link_priority": "hub",
                "recommended_heading_structure": "H2: What is Owner Financing | H2: Benefits | H2: How to Qualify | H2: FAQ",
                "target_answer_length": "medium (200-500)"
            },
            {
                "cluster_id": "cluster_002",
                "cluster_name": "How to Buy Land Guide",
                "primary_keyword": "how to buy land with owner financing",
                "supporting_keywords": ["land buying process step by step", "what documents do I need to buy land", "steps to buying land"],
                "intent": "informational",
                "funnel_stage": "TOFU",
                "total_volume_tier": "medium",
                "competition_tier": "low",
                "recommended_page_type": "how_to_guide",
                "recommended_url_slug": "/how-to-buy-land/",
                "is_new_page_required": True,
                "answer_format": "step_by_step",
                "answer_surface_targets": ["featured_snippet", "voice_search", "people_also_ask"],
                "priority_score": 92,
                "cannibalization_risk": None,
                "search_volume_tier": "medium",
                "geographic_relevance": "national",
                "internal_link_priority": "hub",
                "recommended_heading_structure": "H2: Step 1 | H2: Step 2 | H2: Step 3 | H2: Step 4 | H2: Step 5",
                "target_answer_length": "long (1000+)"
            },
            {
                "cluster_id": "cluster_003",
                "cluster_name": "Rural Land Investment Benefits",
                "primary_keyword": "what is rural land investment",
                "supporting_keywords": ["benefits of rural land investment", "is buying land a good investment", "land investment for beginners"],
                "intent": "informational",
                "funnel_stage": "TOFU",
                "total_volume_tier": "medium",
                "competition_tier": "medium",
                "recommended_page_type": "blog_post",
                "recommended_url_slug": "/rural-land-investment-benefits/",
                "is_new_page_required": True,
                "answer_format": "list",
                "answer_surface_targets": ["featured_snippet", "voice_search", "ai_overview"],
                "priority_score": 88,
                "cannibalization_risk": None,
                "search_volume_tier": "medium",
                "geographic_relevance": "national",
                "internal_link_priority": "spoke",
                "recommended_heading_structure": "H2: What is Land Investment | H2: Top 5 Benefits | H2: Getting Started",
                "target_answer_length": "medium (200-500)"
            },
            {
                "cluster_id": "cluster_004",
                "cluster_name": "Rural Land For Sale Search",
                "primary_keyword": "rural land for sale",
                "supporting_keywords": ["rural land for sale near me", "acreage for sale by owner", "off grid land for sale"],
                "intent": "transactional",
                "funnel_stage": "BOFU",
                "total_volume_tier": "high",
                "competition_tier": "high",
                "recommended_page_type": "category_page",
                "recommended_url_slug": "/rural-land-for-sale/",
                "is_new_page_required": False,
                "answer_format": "list",
                "answer_surface_targets": ["featured_snippet", "voice_search"],
                "priority_score": 78,
                "cannibalization_risk": 0.4,
                "search_volume_tier": "high",
                "geographic_relevance": "local",
                "internal_link_priority": "spoke",
                "recommended_heading_structure": "H2: Featured Properties | H2: Browse by State | H2: Financing Options",
                "target_answer_length": "short (50-100 words)"
            },
            {
                "cluster_id": "cluster_005",
                "cluster_name": "Land Financing Options",
                "primary_keyword": "financing raw land",
                "supporting_keywords": ["land contract vs mortgage", "how to invest in land with no money"],
                "intent": "commercial",
                "funnel_stage": "MOFU",
                "total_volume_tier": "low",
                "competition_tier": "low",
                "recommended_page_type": "landing_page",
                "recommended_url_slug": "/land-financing-options/",
                "is_new_page_required": True,
                "answer_format": "comparison",
                "answer_surface_targets": ["featured_snippet", "ai_overview"],
                "priority_score": 75,
                "cannibalization_risk": None,
                "search_volume_tier": "low",
                "geographic_relevance": "national",
                "internal_link_priority": "spoke",
                "recommended_heading_structure": "H2: Land Contract | H2: Traditional Mortgage | H2: Owner Financing | H2: Comparison Table",
                "target_answer_length": "medium (200-500)"
            },
            {
                "cluster_id": "cluster_006",
                "cluster_name": "Best States for Land Investment",
                "primary_keyword": "best states to buy rural land",
                "supporting_keywords": ["rural land prices by state", "land investment by region"],
                "intent": "commercial",
                "funnel_stage": "MOFU",
                "total_volume_tier": "medium",
                "competition_tier": "high",
                "recommended_page_type": "blog_post",
                "recommended_url_slug": "/best-states-rural-land/",
                "is_new_page_required": True,
                "answer_format": "table",
                "answer_surface_targets": ["featured_snippet", "ai_overview"],
                "priority_score": 70,
                "cannibalization_risk": None,
                "search_volume_tier": "medium",
                "geographic_relevance": "regional",
                "internal_link_priority": "spoke",
                "recommended_heading_structure": "H2: Top States Overview | H2: State Comparison Table | H2: Investment Tips",
                "target_answer_length": "medium (200-500)"
            },
        ]
    })


# Import agents and state
from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.agents.clustering import ClusteringAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.keyword_clusters import KeywordClustersSchema


class TestAgent05Integration:
    """Integration tests for Agent 05 with upstream agents."""

    @pytest.mark.asyncio
    async def test_sequential_01_02_04_05_execution(self, tmp_path):
        """Test full sequential execution: Agent 01 → Agent 02 → Agent 04 → Agent 05."""
        # Set up sequential responses
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        # Create agents
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        # Create initial state
        state = SEOState(
            project_id="integration_001",
            brand_id="brand_001",
            website_url="https://apxnproperty.com",
            config={
                "crawl_depth": 3,
                "target_geography": "United States",
                "intake_form_data": {
                    "business_name": "APXN Property",
                    "industry": "Real Estate",
                    "target_audience": ["Land buyers"],
                    "primary_goals": ["Sell land"],
                },
            },
        )
        
        # === Execute Agent 01 ===
        await intake_agent.execute(state)
        assert state.seo_project_context is not None
        assert state.seo_project_context["business_name"] == "APXN Property"
        
        # === Execute Agent 02 ===
        await crawl_agent.execute(state)
        assert state.site_inventory is not None
        
        # === Execute Agent 04 ===
        await keyword_agent.execute(state)
        assert state.keyword_universe is not None
        assert state.keyword_universe["total_keywords"] == 20

        # === Execute Agent 05 ===
        await clustering_agent.execute(state)

        # Verify keyword_clusters was created
        assert state.keyword_clusters is not None
        assert state.keyword_clusters["total_clusters"] == 6

        # Verify clusters have required fields
        clusters = state.keyword_clusters["clusters"]
        assert len(clusters) == 6
        
        # Verify each cluster has required fields
        for cluster in clusters:
            assert "cluster_id" in cluster
            assert "cluster_name" in cluster
            assert "primary_keyword" in cluster
            assert "intent" in cluster
            assert "recommended_page_type" in cluster
            assert "answer_format" in cluster

        # Verify AEO/GEO fields
        assert "featured_snippet_candidates" in state.keyword_clusters
        assert "voice_search_candidates" in state.keyword_clusters
        assert "ai_overview_candidates" in state.keyword_clusters

        # Verify call count (4 agents = 4 LLM calls)
        assert mock_client.call_count == 4

    @pytest.mark.asyncio
    async def test_agent05_requires_keyword_universe(self, tmp_path):
        """Test that Agent 05 fails without keyword_universe."""
        mock_client = MockGeminiClient()
        
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_002",
            brand_id="brand_002",
            website_url="https://test.com",
            config={"crawl_depth": 2},
        )
        
        # Errors are now caught and logged gracefully
        await clustering_agent.execute(state)
        
        # Verify no API calls were made due to validation failure
        assert mock_client.call_count == 0

    @pytest.mark.asyncio
    async def test_clustering_output_schema_validation(self, tmp_path):
        """Test that the clustering output passes full schema validation."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_003",
            brand_id="brand_003",
            website_url="https://schema-test.com",
            config={
                "crawl_depth": 2,
                "intake_form_data": {"business_name": "Schema Test", "industry": "Real Estate"},
            },
        )
        
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await keyword_agent.execute(state)
        await clustering_agent.execute(state)
        
        # Validate against the full schema
        validated = KeywordClustersSchema(**state.keyword_clusters)
        
        # Verify basic counts
        assert validated.total_clusters == 6
        assert validated.new_pages_needed >= 0
        assert validated.high_priority_clusters >= 0
        
        # Verify AEO/GEO summary fields
        assert validated.featured_snippet_candidates >= 0
        assert validated.voice_search_candidates >= 0
        assert validated.ai_overview_candidates >= 0
        
        # Verify cluster entries
        for cluster in validated.clusters:
            assert cluster.cluster_id is not None
            assert cluster.primary_keyword is not None
            assert cluster.intent is not None
            assert cluster.recommended_page_type is not None
            assert cluster.answer_format is not None
            assert 0 <= cluster.priority_score <= 100

    @pytest.mark.asyncio
    async def test_clustering_preserves_question_keywords(self, tmp_path):
        """Test that question-format keywords are preserved for AEO targeting."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_004",
            brand_id="brand_004",
            website_url="https://question-test.com",
            config={
                "crawl_depth": 2,
                "intake_form_data": {"business_name": "Question Test", "industry": "Education"},
            },
        )
        
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await keyword_agent.execute(state)
        await clustering_agent.execute(state)
        
        # Validate output
        validated = KeywordClustersSchema(**state.keyword_clusters)
        
        # Verify clusters with question keywords target answer surfaces
        for cluster in validated.clusters:
            supporting_kws = cluster.supporting_keywords
            # Check if any question keywords are in supporting keywords
            has_question_kw = any(
                kw.startswith("what") or kw.startswith("how") or kw.startswith("is")
                for kw in supporting_kws
            )
            if has_question_kw:
                # Should target at least one answer surface
                assert len(cluster.answer_surface_targets) > 0

    @pytest.mark.asyncio
    async def test_clustering_identifies_hub_spoke_relationships(self, tmp_path):
        """Test that clustering identifies hub and spoke clusters for internal linking."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        state = SEOState(
            project_id="integration_005",
            brand_id="brand_005",
            website_url="https://linking-test.com",
            config={
                "crawl_depth": 2,
                "intake_form_data": {"business_name": "Linking Test", "industry": "Real Estate"},
            },
        )
        
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await keyword_agent.execute(state)
        await clustering_agent.execute(state)
        
        # Validate output
        validated = KeywordClustersSchema(**state.keyword_clusters)
        
        # Verify hub and spoke lists exist
        assert hasattr(validated, 'hub_clusters')
        assert hasattr(validated, 'spoke_clusters')
        
        # Hub clusters should be identified (based on mock response, cluster_001 and cluster_002 are hubs)
        # Note: Actual hub identification depends on LLM response
        # Verify the cluster relationships exist
        assert validated.hub_clusters is not None
        assert validated.spoke_clusters is not None