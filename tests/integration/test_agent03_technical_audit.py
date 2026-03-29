"""
Test Agent 03 Enhancements - Technical Audit Agent

This test specifically validates enhancements made to Agent 03:
1. Inference-based analysis focus (not programmatic)
2. Input validation (requires site_inventory from Agent 02)
3. Schema validation with Pydantic
4. Programmatic summary from Agent 02 data
5. Health score calculation

IMPORTANT: Agent 02 handles programmatic detection (duplicates, missing meta, etc.)
Agent 03 focuses ONLY on inference-based analysis.

Run with:
    pytest tests/integration/test_agent03_technical_audit.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from seo_agents.agents.technical import TechnicalAuditAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.technical_audit_report import (
    TechnicalAuditReportSchema,
    InferenceIssue,
    ProgrammaticSummary,
)


# ================= EDGE CASE MOCK RESPONSES =================

def get_mock_technical_audit_response_inference_only() -> str:
    """Mock response with only inference issues (no programmatic details)."""
    return json.dumps({
        "total_inference_issues": 2,
        "inference_critical": [
            {
                "issue_type": "content_quality",
                "severity": "critical",
                "affected_urls": ["https://example.com/blog/old-post"],
                "description": " Blog content does not match SaaS industry focus",
                "recommendation": "Update blog to focus on SaaS/marketing topics"
            }
        ],
        "inference_warnings": [
            {
                "issue_type": "semantic_mismatch",
                "severity": "warning", 
                "affected_urls": ["https://example.com/about"],
                "description": "Page title mentions 'team' but content focuses on 'history'",
                "recommendation": "Align title with actual content focus"
            }
        ],
        "inference_info": [],
        "programmatic_summary": None,  # Should be extracted from Agent 02 data
        "overall_health_score": 85
    })


def get_mock_technical_audit_response_with_programmatic() -> str:
    """Mock response with programmatic summary included."""
    return json.dumps({
        "total_inference_issues": 1,
        "inference_critical": [],
        "inference_warnings": [
            {
                "issue_type": "architecture",
                "severity": "warning",
                "affected_urls": ["https://example.com/pricing"],
                "description": "Pricing page has no incoming internal links",
                "recommendation": "Add links from feature comparison pages"
            }
        ],
        "inference_info": [
            {
                "issue_type": "accessibility",
                "severity": "info",
                "affected_urls": ["https://example.com/contact"],
                "description": "Contact form images have generic alt text",
                "recommendation": "Use descriptive alt text for form icons"
            }
        ],
        "programmatic_summary": {
            "duplicate_titles_count": 2,
            "duplicate_meta_count": 3,
            "thin_content_count": 5,
            "pages_missing_h1_count": 10,
            "pages_missing_meta_count": 15,
            "broken_links_count": 3
        },
        "overall_health_score": 72
    })


def get_mock_technical_audit_response_missing_fields() -> str:
    """Mock response with missing optional fields (should get defaults)."""
    return json.dumps({
        "inference_critical": [
            {
                "issue_type": "content_quality",
                "severity": "critical",
                "affected_urls": None,  # None should become []
                "description": "Low quality content detected",
                "recommendation": "Improve content"
            }
        ],
        "inference_warnings": [],
        "inference_info": [],
        # Missing programmatic_summary - should be extracted from Agent 02
        # Missing overall_health_score - should be calculated
    })


def get_mock_inventory_for_agent_02() -> dict:
    """Mock site inventory that would come from Agent 02."""
    return {
        "total_pages": 50,
        "crawl_depth_reached": 3,
        "pages_with_h1": 45,
        "pages_with_meta_description": 35,
        "pages_with_schema": 20,
        "duplicate_titles": [
            {"url": "https://example.com/page1", "title": "Duplicate Title"},
            {"url": "https://example.com/page2", "title": "Duplicate Title"}
        ],
        "duplicate_meta_descriptions": [
            {"url": "https://example.com/page3", "meta_description": "Same description"},
            {"url": "https://example.com/page4", "meta_description": "Same description"},
            {"url": "https://example.com/page5", "meta_description": "Same description"}
        ],
        "thin_content_pages": [
            {"url": "https://example.com/empty", "word_count": 50},
            {"url": "https://example.com/short", "word_count": 80},
        ],
        "pages": [
            {"url": "https://example.com/", "status_code": 200, "title": "Home", "word_count": 500},
            {"url": "https://example.com/about", "status_code": 200, "title": "About", "word_count": 300},
            {"url": "https://example.com/404", "status_code": 404, "title": "Not Found", "word_count": 0},
        ]
    }


# ================= TEST CLASS =================

class TestAgent03TechnicalAuditEnhancements:
    """Tests for Agent 03 enhancements - inference-based technical audit."""

    @pytest.mark.asyncio
    async def test_inference_focus_only(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 1: Agent 03 focuses on inference, not programmatic.
        
        Agent 02 handles programmatic detection. Agent 03 should NOT
        report duplicates, missing meta, etc. - it should focus on:
        - content_quality
        - semantic_mismatch  
        - accessibility
        - architecture
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_technical_audit_response_inference_only())
        
        state = SEOState(
            project_id="enhancement_test_03_001",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={
                "business_name": "Example Corp",
                "website_url": "https://example.com",
                "industry": "SaaS",
                "target_audience": ["SMBs"],
                "primary_goals": ["Increase traffic"],
            },
            site_inventory=get_mock_inventory_for_agent_02(),
            config={"crawl_depth": 3, "max_pages": 500},
            completed_agents=["agent_01_intake", "agent_02_crawl"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        assert state.technical_audit_report is not None
        
        # Check inference issues are present
        report = state.technical_audit_report
        assert report["total_inference_issues"] == 2
        assert len(report["inference_critical"]) == 1
        assert report["inference_critical"][0]["issue_type"] == "content_quality"
        
        print("\n✓ Enhancement Test 1 PASSED: Agent 03 focuses on inference-based issues!")

    @pytest.mark.asyncio
    async def test_programmatic_summary_extraction(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 2: Agent 03 extracts programmatic summary from Agent 02 data.
        
        Even if LLM doesn't provide programmatic_summary, Agent 03 should
        extract it from the site_inventory.
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_technical_audit_response_with_programmatic())
        
        state = SEOState(
            project_id="enhancement_test_03_002",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={
                "business_name": "Example Corp",
                "website_url": "https://example.com",
                "industry": "SaaS",
            },
            site_inventory=get_mock_inventory_for_agent_02(),
            config={"crawl_depth": 3},
            completed_agents=["agent_01_intake", "agent_02_crawl"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        report = state.technical_audit_report
        prog_summary = report["programmatic_summary"]
        
        # LLM provided values should be kept (when available)
        # Missing values are filled from Agent 02 inventory
        # LLM provided thin_content_count: 5, but missing pages_with_meta_count is filled: 50-35=15
        assert prog_summary["duplicate_titles_count"] == 2
        assert prog_summary["duplicate_meta_count"] == 3
        assert prog_summary["thin_content_count"] == 5  # LLM value kept
        
        print("\n✓ Enhancement Test 2 PASSED: Programmatic summary extracted!")

    @pytest.mark.asyncio
    async def test_none_to_list_normalization(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 3: None values normalized to [] for affected_urls.
        
        If LLM returns affected_urls: None, it should become []
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_technical_audit_response_missing_fields())
        
        state = SEOState(
            project_id="enhancement_test_03_003",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={
                "business_name": "Example Corp",
                "website_url": "https://example.com",
                "industry": "SaaS",
            },
            site_inventory=get_mock_inventory_for_agent_02(),
            config={"crawl_depth": 3},
            completed_agents=["agent_01_intake", "agent_02_crawl"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert
        report = state.technical_audit_report
        
        # Check None → [] normalization
        critical = report["inference_critical"][0]
        assert critical["affected_urls"] == [], f"affected_urls should be [], got {critical['affected_urls']}"
        
        print("\n✓ Enhancement Test 3 PASSED: None → [] normalization works!")

    @pytest.mark.asyncio
    async def test_schema_validation(
        self,
        test_storage_dir: Path,
    ):
        """
        Enhancement Test 4: Output validates against Pydantic schema.
        
        The final output should be a valid TechnicalAuditReportSchema
        """
        # Arrange
        mock_client = MockGeminiClient(get_mock_technical_audit_response_with_programmatic())
        
        state = SEOState(
            project_id="enhancement_test_03_004",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={
                "business_name": "Example Corp",
                "website_url": "https://example.com",
                "industry": "SaaS",
            },
            site_inventory=get_mock_inventory_for_agent_02(),
            config={"crawl_depth": 3},
            completed_agents=["agent_01_intake", "agent_02_crawl"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act
        await agent.execute(state)
        
        # Assert - Validate against schema
        validated = TechnicalAuditReportSchema(**state.technical_audit_report)
        
        assert validated.total_inference_issues >= 0
        assert 0 <= validated.overall_health_score <= 100
        assert isinstance(validated.inference_critical, list)
        assert isinstance(validated.programmatic_summary, ProgrammaticSummary)
        
        print("\n✓ Enhancement Test 4 PASSED: Schema validation works!")


# ================= INPUT VALIDATION TESTS =================

class TestAgent03InputValidation:
    """Tests for Agent 03 input validation."""

    @pytest.mark.asyncio
    async def test_missing_site_inventory(
        self,
        test_storage_dir: Path,
    ):
        """Test that missing site_inventory raises ValueError."""
        # Arrange
        mock_client = MockGeminiClient("{}")
        
        state = SEOState(
            project_id="input_test_03_001",
            brand_id="brand_001",
            website_url="https://example.com",
            seo_project_context={"website_url": "https://example.com"},
            # site_inventory is missing
            completed_agents=["agent_01_intake"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act & Assert
        with pytest.raises(ValueError, match="site_inventory required"):
            await agent.execute(state)
        
        print("\n✓ Input Validation Test 1 PASSED: Missing site_inventory detected!")

    @pytest.mark.asyncio
    async def test_missing_seo_project_context(
        self,
        test_storage_dir: Path,
    ):
        """Test that missing seo_project_context raises ValueError."""
        # Arrange
        mock_client = MockGeminiClient("{}")
        
        state = SEOState(
            project_id="input_test_03_002",
            brand_id="brand_001",
            website_url="https://example.com",
            site_inventory=get_mock_inventory_for_agent_02(),
            # seo_project_context is missing
            completed_agents=["agent_01_intake", "agent_02_crawl"],
        )
        
        agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        # Act & Assert
        with pytest.raises(ValueError, match="seo_project_context required"):
            await agent.execute(state)
        
        print("\n✓ Input Validation Test 2 PASSED: Missing seo_project_context detected!")


# ================= HELPER MOCK CLASS =================

class MockGeminiClient:
    """Mock Gemini client for testing."""
    
    def __init__(self, response: str):
        self._response = response
    
    async def generate_content_async(self, model: str, contents: str):
        class Response:
            def __init__(self, text):
                self.text = text
        return Response(self._response)


# ================= PYTEST FIXTURES =================

import tempfile
from pathlib import Path

@pytest.fixture
def test_storage_dir():
    """Create a temporary storage directory for each test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)