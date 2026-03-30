"""
Integration test for full pipeline: Agent 01 → Agent 02 → Agent 03 → Agent 04 → Agent 05

This test validates:
1. Agent 01 produces seo_project_context
2. Agent 02 produces site_inventory
3. Agent 03 produces technical_audit_report (after Gate 1 approval)
4. Agent 04 produces keyword_universe
5. Agent 05 produces keyword_clusters with AEO/GEO optimizations

Run with:
    pytest tests/integration/test_pipeline_01_to_05.py -v
"""

from __future__ import annotations

import json
import pytest


# MockGeminiClient class (same as in conftest.py)
class MockGeminiResponse:
    """Mock response object mimicking Gemini API response."""
    
    def __init__(self, text: str):
        self.text = text


class MockModels:
    def __init__(self, parent):
        self.parent = parent
        
    def generate_content(self, model: str = None, contents: str = None, **kwargs):
        self.parent._call_count += 1
        if self.parent._responses and self.parent._response_index < len(self.parent._responses):
            response = self.parent._responses[self.parent._response_index]
            self.parent._response_index += 1
            return MockGeminiResponse(text=response)
        return MockGeminiResponse(text=json.dumps({}))

class MockGeminiClient:
    """Mock Gemini client for testing."""
    
    def __init__(self):
        self._responses = []
        self._response_index = 0
        self._call_count = 0
        self.models = MockModels(self)
    
    def set_responses(self, responses):
        self._responses = responses
        self._response_index = 0
    
    @property
    def call_count(self):
        return self._call_count


# ================= MOCK RESPONSES =================

def get_mock_intake_response():
    """Mock response for Agent 01 Intake."""
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
    """Mock response for Agent 02 Crawl."""
    return json.dumps({
        "total_pages": 14,
        "crawl_depth_reached": 3,
        "pages": [
            {"url": "https://apxnproperty.com/", "status_code": 200, "title": "APXN Property - Rural Land Investment", "meta_description": "Buy rural land with owner financing", "h1": "APXN Property", "word_count": 500, "response_time_ms": 150, "internal_links": ["https://apxnproperty.com/about", "https://apxnproperty.com/investments"], "external_links": []},
            {"url": "https://apxnproperty.com/about", "status_code": 200, "title": "About Us", "meta_description": "About APXN Property", "h1": "About Us", "word_count": 300, "response_time_ms": 120, "internal_links": ["https://apxnproperty.com/"], "external_links": []},
            {"url": "https://apxnproperty.com/investments", "status_code": 200, "title": "Land Investments", "meta_description": "Available land investments", "h1": "Our Land Investments", "word_count": 800, "response_time_ms": 180, "internal_links": ["https://apxnproperty.com/"], "external_links": []},
        ],
        "crawl_errors": [],
    })


def get_mock_technical_response():
    """Mock response for Agent 03 Technical Audit."""
    return json.dumps({
        "total_inference_issues": 3,
        "inference_critical": [],
        "inference_warnings": [
            {
                "issue_type": "missing_schema",
                "severity": "warning",
                "affected_urls": ["https://apxnproperty.com/"],
                "description": "No structured data found on homepage",
                "recommendation": "Add JSON-LD schema for organization"
            },
            {
                "issue_type": "performance",
                "severity": "warning",
                "affected_urls": ["https://apxnproperty.com/investments"],
                "description": "Response time exceeds 200ms threshold",
                "recommendation": "Optimize images and enable caching"
            }
        ],
        "inference_info": [
            {
                "issue_type": "accessibility",
                "severity": "info",
                "affected_urls": [],
                "description": "Some images may be missing alt text",
                "recommendation": "Review image alt text coverage"
            }
        ],
        "programmatic_summary": {
            "duplicate_titles_count": 0,
            "duplicate_meta_count": 0,
            "thin_content_count": 0,
            "pages_missing_h1_count": 0,
            "pages_missing_meta_count": 0,
            "broken_links_count": 0
        },
        "overall_health_score": 78,
        "answer_readiness_score": 65,
        "citation_trust_score": 60,
        "voice_search_readiness": "needs_improvement",
        "aeo_recommendations": ["Add FAQ schema to informational pages", "Implement HowTo schema for guides"],
        "geo_recommendations": ["Increase content depth on key pages", "Add authoritative citations"],
        "schema_quality_for_ai": "basic"
    })


def get_mock_keyword_response():
    """Mock response for Agent 04 Keyword Research with AEO/GEO fields."""
    return json.dumps({
        "total_keywords": 20,
        "keywords": [
            {"keyword": "rural land for sale", "intent": "transactional", "volume_tier": "high", "competition_tier": "high", "source": "seed", "query_format": "keyword", "answer_surfaces": ["featured_snippet", "voice_search"], "citation_value_score": 6},
            {"keyword": "owner financing land", "intent": "commercial", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["ai_overview"], "citation_value_score": 8},
            {"keyword": "how to buy land with owner financing", "intent": "informational", "volume_tier": "medium", "competition_tier": "low", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search", "ai_overview"], "citation_value_score": 9},
            {"keyword": "cheap land for sale owner financing", "intent": "transactional", "volume_tier": "medium", "competition_tier": "medium", "source": "expansion", "query_format": "keyword", "answer_surfaces": ["featured_snippet"], "citation_value_score": 9},
            {"keyword": "what is rural land investment", "intent": "informational", "volume_tier": "low", "competition_tier": "medium", "source": "question_variant", "query_format": "question", "answer_surfaces": ["featured_snippet", "voice_search", "ai_overview"], "citation_value_score": 9},
        ],
        "seed_terms_used": ["rural land", "owner financing", "land buying guides"],
        "featured_snippet_opportunities": 9,
        "voice_search_opportunities": 6,
        "ai_overview_opportunities": 8,
        "high_citation_value_keywords": 6,
    })


def get_mock_clustering_response():
    """Mock response for Agent 05 Clustering."""
    return json.dumps({
        "total_clusters": 3,
        "clusters": [
            {
                "cluster_id": "cluster_001",
                "cluster_name": "Owner Financing Land Purchase",
                "primary_keyword": "owner financing land",
                "supporting_keywords": ["cheap land for sale owner financing", "land contract financing"],
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
                "recommended_heading_structure": "H2: What is Owner Financing | H2: Benefits | H2: FAQ",
                "target_answer_length": "medium (200-500)"
            },
            {
                "cluster_id": "cluster_002",
                "cluster_name": "How to Buy Land Guide",
                "primary_keyword": "how to buy land with owner financing",
                "supporting_keywords": ["land buying process step by step", "what documents do I need to buy land"],
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
                "recommended_heading_structure": "H2: Step 1 | H2: Step 2 | H2: Step 3",
                "target_answer_length": "long (1000+)"
            },
            {
                "cluster_id": "cluster_003",
                "cluster_name": "Rural Land For Sale Search",
                "primary_keyword": "rural land for sale",
                "supporting_keywords": ["rural land for sale near me", "acreage for sale by owner"],
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
                "recommended_heading_structure": "H2: Featured Properties | H2: Browse by State",
                "target_answer_length": "short (50-100 words)"
            },
        ],
    })


# ================= IMPORT AGENTS =================

# Import agents and state
from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.technical import TechnicalAuditAgent
from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.agents.clustering import ClusteringAgent
from seo_agents.state import SEOState


class TestPipeline01To05:
    """Integration tests for full pipeline: Agent 01 → 02 → 03 → 04 → 05."""

    @pytest.mark.asyncio
    async def test_full_pipeline_01_to_05_execution(self, tmp_path):
        """Test full sequential execution: Agent 01 → Agent 02 → Agent 03 → Agent 04 → Agent 05."""
        # Set up sequential responses (5 agents = 5 LLM calls)
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),       # Agent 01
            get_mock_crawl_response(),         # Agent 02
            get_mock_technical_response(),     # Agent 03
            get_mock_keyword_response(),       # Agent 04
            get_mock_clustering_response(),    # Agent 05
        ])
        
        # Create agents
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        technical_agent = TechnicalAuditAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        # Create initial state
        state = SEOState(
            project_id="pipeline_001",
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
        
        # === Execute Agent 01 (Intake) ===
        print("\n[TEST] Executing Agent 01 - Intake...")
        await intake_agent.execute(state)
        
        assert state.seo_project_context is not None, "Agent 01 should produce seo_project_context"
        assert state.seo_project_context["business_name"] == "APXN Property"
        assert "competitors" in state.seo_project_context
        print(f"  ✓ Agent 01 complete: business_name = {state.seo_project_context['business_name']}")
        
        # === Execute Agent 02 (Crawl) ===
        print("[TEST] Executing Agent 02 - Crawl...")
        await crawl_agent.execute(state)
        
        assert state.site_inventory is not None, "Agent 02 should produce site_inventory"
        assert state.site_inventory["total_pages"] == 14
        print(f"  ✓ Agent 02 complete: total_pages = {state.site_inventory['total_pages']}")
        
        # === Execute Agent 03 (Technical) ===
        print("[TEST] Executing Agent 03 - Technical Audit...")
        await technical_agent.execute(state)
        
        assert state.technical_audit_report is not None, "Agent 03 should produce technical_audit_report"
        assert state.technical_audit_report["overall_health_score"] == 78
        print(f"  ✓ Agent 03 complete: health_score = {state.technical_audit_report['overall_health_score']}")
        
        # === Execute Agent 04 (Keywords) ===
        print("[TEST] Executing Agent 04 - Keyword Research...")
        await keyword_agent.execute(state)
        
        assert state.keyword_universe is not None, "Agent 04 should produce keyword_universe"
        assert state.keyword_universe["total_keywords"] == 20
        print(f"  ✓ Agent 04 complete: total_keywords = {state.keyword_universe['total_keywords']}")
        
        # === Execute Agent 05 (Clustering) ===
        print("[TEST] Executing Agent 05 - Clustering...")
        await clustering_agent.execute(state)
        
        assert state.keyword_clusters is not None, "Agent 05 should produce keyword_clusters"
        assert state.keyword_clusters["total_clusters"] == 3
        print(f"  ✓ Agent 05 complete: total_clusters = {state.keyword_clusters['total_clusters']}")
        
        # ================= VERIFY FINAL OUTPUT =================
        
        # Verify all agents produced output
        outputs = {
            "seo_project_context": state.seo_project_context is not None,
            "site_inventory": state.site_inventory is not None,
            "technical_audit_report": state.technical_audit_report is not None,
            "keyword_universe": state.keyword_universe is not None,
            "keyword_clusters": state.keyword_clusters is not None,
        }
        
        print("\n[TEST] Pipeline Output Summary:")
        for output_name, exists in outputs.items():
            status = "✓" if exists else "✗"
            print(f"  {status} {output_name}: {exists}")
        
        # Verify keyword_clusters structure
        clusters = state.keyword_clusters["clusters"]
        assert len(clusters) == 3
        
        # Verify each cluster has required fields
        for cluster in clusters:
            assert "cluster_id" in cluster
            assert "cluster_name" in cluster
            assert "primary_keyword" in cluster
            assert "intent" in cluster
            assert "recommended_page_type" in cluster
            assert "answer_format" in cluster
            assert "answer_surface_targets" in cluster
            assert "internal_link_priority" in cluster
        
        # Verify AEO/GEO summary fields
        assert "featured_snippet_candidates" in state.keyword_clusters
        assert "voice_search_candidates" in state.keyword_clusters
        assert "ai_overview_candidates" in state.keyword_clusters
        
        # Verify hub/spoke relationships
        hub_clusters = [c for c in clusters if c.get("internal_link_priority") == "hub"]
        spoke_clusters = [c for c in clusters if c.get("internal_link_priority") == "spoke"]
        
        assert len(hub_clusters) >= 1, "Should have at least one hub cluster"
        assert len(spoke_clusters) >= 1, "Should have at least one spoke cluster"
        
        print(f"\n[TEST] Hub/Spoke Analysis:")
        print(f"  Hub clusters: {[c['cluster_id'] for c in hub_clusters]}")
        print(f"  Spoke clusters: {[c['cluster_id'] for c in spoke_clusters]}")
        
        # Verify call count (5 agents = 5 LLM calls)
        assert mock_client.call_count == 5, f"Expected 5 LLM calls, got {mock_client.call_count}"
        
        print(f"\n[TEST] ✓ ALL TESTS PASSED!")
        print(f"  Total LLM calls: {mock_client.call_count}")
        print(f"  Pipeline completed: Agent 01 → 02 → 03 → 04 → 05")

    @pytest.mark.asyncio
    async def test_pipeline_state_updates(self, tmp_path):
        """Test that state is properly updated throughout the pipeline."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_technical_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        # Create agents
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        technical_agent = TechnicalAuditAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        # Create initial state
        state = SEOState(
            project_id="pipeline_002",
            brand_id="brand_002",
            website_url="https://test.com",
            config={"crawl_depth": 3},
        )
        
        # Execute pipeline
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await technical_agent.execute(state)
        await keyword_agent.execute(state)
        await clustering_agent.execute(state)
        
        # Verify state status progression
        # After Agent 01: status should be 'intelligence'
        assert state.status == "intelligence"
        
        # Verify all outputs were produced
        assert state.seo_project_context is not None, "seo_project_context should be set"
        assert state.site_inventory is not None, "site_inventory should be set"
        assert state.technical_audit_report is not None, "technical_audit_report should be set"
        assert state.keyword_universe is not None, "keyword_universe should be set"
        assert state.keyword_clusters is not None, "keyword_clusters should be set"
        
        # Verify LLM calls were made for each agent
        assert mock_client.call_count == 5, f"Expected 5 LLM calls, got {mock_client.call_count}"
        
        print(f"\n[TEST] State progression:")
        print(f"  Status: {state.status}")
        print("  All 5 outputs produced: ✓")
        
    @pytest.mark.asyncio
    async def test_pipeline_preserves_aeo_geo_fields(self, tmp_path):
        """Test that AEO/GEO fields are properly preserved throughout the pipeline."""
        mock_client = MockGeminiClient()
        mock_client.set_responses([
            get_mock_intake_response(),
            get_mock_crawl_response(),
            get_mock_technical_response(),
            get_mock_keyword_response(),
            get_mock_clustering_response(),
        ])
        
        # Create agents
        intake_agent = IntakeAgent(mock_client, "test-model", tmp_path)
        crawl_agent = CrawlAgent(mock_client, "test-model", tmp_path)
        technical_agent = TechnicalAuditAgent(mock_client, "test-model", tmp_path)
        keyword_agent = KeywordResearchAgent(mock_client, "test-model", tmp_path)
        clustering_agent = ClusteringAgent(mock_client, "test-model", tmp_path)
        
        # Create initial state
        state = SEOState(
            project_id="pipeline_003",
            brand_id="brand_003",
            website_url="https://test.com",
            config={"crawl_depth": 3},
        )
        
        # Execute pipeline
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await technical_agent.execute(state)
        await keyword_agent.execute(state)
        await clustering_agent.execute(state)
        
        # Verify AEO/GEO fields from Agent 04 (Keywords) passed to Agent 05 (Clustering)
        keyword_universe = state.keyword_universe
        assert "featured_snippet_opportunities" in keyword_universe
        assert "voice_search_opportunities" in keyword_universe
        assert "ai_overview_opportunities" in keyword_universe
        
        # Verify AEO/GEO fields in keyword_clusters from Agent 05
        keyword_clusters = state.keyword_clusters
        
        # Check that clusters have answer_surface_targets
        for cluster in keyword_clusters["clusters"]:
            assert "answer_surface_targets" in cluster
            assert len(cluster["answer_surface_targets"]) > 0
        
        # Check summary fields
        assert keyword_clusters["featured_snippet_candidates"] > 0
        assert keyword_clusters["voice_search_candidates"] >= 0
        assert keyword_clusters["ai_overview_candidates"] >= 0
        
        print(f"\n[TEST] AEO/GEO Pipeline Preservation:")
        print(f"  Keyword universe - Featured Snippet: {keyword_universe['featured_snippet_opportunities']}")
        print(f"  Keyword clusters - Featured Snippet candidates: {keyword_clusters['featured_snippet_candidates']}")
