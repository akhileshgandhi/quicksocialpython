"""
Sequential Test: Agent 01 + Agent 02 + Agent 03 Pipeline

This test verifies all three agents work together in sequence:
1. Run Agent 01 (Intake) - produces seo_project_context
2. Run Agent 02 (Crawl) - consumes seo_project_context, produces site_inventory
3. Run Agent 03 (Technical Audit) - consumes site_inventory + seo_project_context, produces technical_audit_report

IMPORTANT: Agent 02 handles programmatic detection (duplicates, missing meta, etc.)
Agent 03 focuses ONLY on inference-based analysis.

Run with:
    pytest tests/integration/test_agent01_to_agent03_sequential.py -v
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pytest

from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.technical import TechnicalAuditAgent
from seo_agents.state import SEOState
from seo_agents.validators.schemas.seo_project_context import SEOProjectContextSchema
from seo_agents.validators.schemas.site_inventory import SiteInventorySchema
from seo_agents.validators.schemas.technical_audit_report import TechnicalAuditReportSchema


# ================= MOCK RESPONSES =================

def get_mock_intake_response() -> str:
    """Mock response for Agent 01."""
    return json.dumps({
        "business_name": "Acme Corporation",
        "website_url": "https://acme-test.example.com",
        "industry": "Technology",
        "target_audience": ["Enterprises", "Developers", "SMBs"],
        "primary_goals": ["Increase organic traffic", "Generate leads", "Build brand awareness"],
        "geographic_focus": "North America",
        "competitors": ["competitor1.com", "competitor2.com"],
        "brand_voice": "Professional, innovative, trustworthy",
        "key_products_services": ["Cloud Platform", "API Services", "Developer Tools"],
    })


def get_mock_crawl_response() -> str:
    """Mock response for Agent 02."""
    return json.dumps({
        "total_pages": 10,
        "crawl_depth_reached": 2,
        "pages_with_h1": 8,
        "pages_with_meta_description": 7,
        "pages_with_schema": 4,
        "pages": [
            {
                "url": "https://acme-test.example.com/",
                "status_code": 200,
                "title": "Acme Corporation - Home",
                "meta_description": "Leading provider of cloud solutions",
                "h1": "Acme Corporation",
                "h2_tags": ["Our Services", "Why Choose Us"],
                "h3_tags": ["Cloud Platform", "API Services"],
                "canonical_url": "https://acme-test.example.com/",
                "is_https": True,
                "robots_directive": "index, follow",
                "og_tags": {
                    "og_title": "Acme Corporation",
                    "og_description": "Leading provider of cloud solutions",
                    "og_image": "https://acme-test.example.com/og-image.png",
                    "og_url": "https://acme-test.example.com/",
                    "og_type": "website",
                    "og_site_name": "Acme Corporation"
                },
                "schema_markup": '{"@context": "https://schema.org", "@type": "Organization"}',
                "schema_types": ["Organization"],
                "word_count": 500,
                "response_time_ms": 150,
                "images": [
                    {"src": "https://acme-test.example.com/hero.jpg", "alt": "Hero image", "width": 1200, "height": 630, "is_optimized": True}
                ],
                "has_unoptimized_images": False,
                "internal_links": ["/about", "/products", "/contact"],
                "external_links": ["https://partner.example.com"]
            },
            {
                "url": "https://acme-test.example.com/about",
                "status_code": 200,
                "title": "About Us - Acme Corporation",
                "meta_description": "Learn about our mission and values",
                "h1": "About Acme",
                "h2_tags": ["Our Mission", "Our Team"],
                "h3_tags": [],
                "canonical_url": "https://acme-test.example.com/about",
                "is_https": True,
                "robots_directive": "index, follow",
                "og_tags": None,
                "schema_markup": None,
                "schema_types": [],
                "word_count": 350,
                "response_time_ms": 120,
                "images": [],
                "has_unoptimized_images": False,
                "internal_links": ["/"],
                "external_links": []
            },
            {
                "url": "https://acme-test.example.com/products",
                "status_code": 200,
                "title": "Products - Acme Corporation",
                "meta_description": "Explore our product offerings",
                "h1": "Products",
                "h2_tags": ["Cloud Platform", "API Services"],
                "h3_tags": [],
                "canonical_url": "https://acme-test.example.com/products",
                "is_https": True,
                "robots_directive": "index, follow",
                "og_tags": None,
                "schema_markup": '{"@context": "https://schema.org", "@type": "Product"}',
                "schema_types": ["Product"],
                "word_count": 800,
                "response_time_ms": 200,
                "images": [],
                "has_unoptimized_images": False,
                "internal_links": ["/"],
                "external_links": []
            },
        ],
        "duplicate_titles": [
            {"url": "https://acme-test.example.com/about", "title": "About Us - Acme Corporation"},
            {"url": "https://acme-test.example.com/contact", "title": "About Us - Acme Corporation"}
        ],
        "duplicate_meta_descriptions": [
            {"url": "https://acme-test.example.com/about", "meta_description": "Learn about our mission and values"},
            {"url": "https://acme-test.example.com/contact", "meta_description": "Learn about our mission and values"}
        ],
        "thin_content_pages": [
            {"url": "https://acme-test.example.com/404", "word_count": "20"}
        ],
        "sitemap": {
            "found": True,
            "url": "https://acme-test.example.com/sitemap.xml",
            "pages_count": 10
        },
        "robots_txt": {
            "found": True,
            "url": "https://acme-test.example.com/robots.txt",
            "allows_crawl": True,
            "sitemaps": ["https://acme-test.example.com/sitemap.xml"]
        },
        "is_https_only": True,
        "has_ssl_issues": False,
    })


def get_mock_technical_audit_response() -> str:
    """Mock response for Agent 03.
    
    IMPORTANT: Agent 03 focuses on INFERENCE-based issues only.
    Programmatic issues should come from Agent 02 (referenced in programmatic_summary).
    """
    return json.dumps({
        "total_inference_issues": 2,
        "inference_critical": [
            {
                "issue_type": "content_quality",
                "severity": "critical",
                "affected_urls": ["https://acme-test.example.com/about"],
                "description": "About page content discusses historical milestones but industry is Technology - potential semantic mismatch",
                "recommendation": "Update content to focus on technology solutions or move to a separate 'history' page"
            }
        ],
        "inference_warnings": [
            {
                "issue_type": "architecture",
                "severity": "warning",
                "affected_urls": ["https://acme-test.example.com/products"],
                "description": "Products page has no incoming internal links from other pages",
                "recommendation": "Add links from homepage and service pages to improve navigation flow"
            }
        ],
        "inference_info": [
            {
                "issue_type": "accessibility",
                "severity": "info",
                "affected_urls": ["https://acme-test.example.com/contact"],
                "description": "Contact page uses generic alt text for icons",
                "recommendation": "Use descriptive alt text like 'Email icon' instead of 'icon'"
            }
        ],
        "programmatic_summary": {
            "duplicate_titles_count": 2,
            "duplicate_meta_count": 2,
            "thin_content_count": 1,
            "pages_missing_h1_count": 2,
            "pages_missing_meta_count": 3,
            "broken_links_count": 0
        },
        "overall_health_score": 78
    })


# ================= MOCK CLIENT =================

class MockGeminiClient:
    """Mock Gemini client that returns different responses based on agent type."""
    
    def __init__(self):
        self._responses = {
            "intake": get_mock_intake_response(),
            "crawl": get_mock_crawl_response(),
            "technical": get_mock_technical_audit_response(),
        }
        self._call_count = 0
    
    async def generate_content_async(self, model: str, contents: str) -> Any:
        self._call_count += 1
        
        # Determine which response to return based on prompt content
        contents_lower = contents.lower()
        
        if "intake" in contents_lower or "business" in contents_lower:
            response_text = self._responses["intake"]
        elif "crawl" in contents_lower or "site inventory" in contents_lower:
            response_text = self._responses["crawl"]
        elif "technical" in contents_lower or "inference" in contents_lower:
            response_text = self._responses["technical"]
        else:
            # Default to technical response for Agent 03
            response_text = self._responses["technical"]
        
        class Response:
            def __init__(self, text):
                self.text = text
        
        return Response(response_text)
    
    @property
    def call_count(self) -> int:
        return self._call_count


# ================= TEST FIXTURES =================

@pytest.fixture
def mock_gemini():
    """Create a fresh mock Gemini client."""
    return MockGeminiClient()


@pytest.fixture
def test_storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory."""
    storage = tmp_path / "seo_sequential_test"
    storage.mkdir(exist_ok=True)
    return storage


# ================= SEQUENTIAL TESTS =================

class TestAgent01ToAgent03Sequential:
    """Sequential tests for Agent 01 → Agent 02 → Agent 03 pipeline."""
    
    @pytest.mark.asyncio
    async def test_sequential_agent01_to_agent02_to_agent03(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Sequential Test: Run Agent 01, then Agent 02, then Agent 03
        
        Verifies:
        1. Agent 01 produces seo_project_context
        2. Agent 02 consumes seo_project_context, produces site_inventory
        3. Agent 03 consumes site_inventory + seo_project_context, produces technical_audit_report
        4. All three agents complete successfully in sequence
        5. Data flows correctly from one agent to the next
        """
        # Arrange
        state = SEOState(
            project_id="sequential_test_001",
            brand_id="brand_seq_001",
            website_url="https://acme-test.example.com",
            config={
                "crawl_depth": 2,
                "target_geography": "North America",
                "max_pages": 50,
                "intake_form_data": {
                    "business_name": "Acme Corporation",
                    "industry": "Technology",
                    "target_audience": ["Enterprises", "Developers"],
                    "primary_goals": ["Increase traffic", "Generate leads"],
                },
            },
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Create all three agents
        intake_agent = IntakeAgent(mock_gemini, "test-model", test_storage_dir)
        crawl_agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        technical_agent = TechnicalAuditAgent(mock_gemini, "test-model", test_storage_dir)
        
        # ========== STEP 1: Run Agent 01 (Intake) ==========
        print("\n[STEP 1] Running Agent 01 (Intake)...")
        
        await intake_agent.execute(state)
        
        # Assert - Agent 01 output
        assert state.seo_project_context is not None, "Agent 01 should produce seo_project_context"
        assert state.seo_project_context["website_url"] == "https://acme-test.example.com"
        assert state.seo_project_context["business_name"] == "Acme Corporation"
        assert state.seo_project_context["industry"] == "Technology"
        
        # Verify schema
        validated_context = SEOProjectContextSchema(**state.seo_project_context)
        assert validated_context.business_name == "Acme Corporation"
        
        print(f"  ✓ Agent 01 complete: {validated_context.business_name}")
        print(f"    - Industry: {validated_context.industry}")
        print(f"    - Website: {validated_context.website_url}")
        
        # ========== STEP 2: Run Agent 02 (Crawl) ==========
        print("\n[STEP 2] Running Agent 02 (Crawl)...")
        
        await crawl_agent.execute(state)
        
        # Assert - Agent 02 output
        assert state.site_inventory is not None, "Agent 02 should produce site_inventory"
        assert state.site_inventory["total_pages"] > 0
        assert len(state.site_inventory["pages"]) > 0
        
        # Verify schema
        validated_inventory = SiteInventorySchema(**state.site_inventory)
        assert validated_inventory.total_pages == 10
        assert validated_inventory.crawl_depth_reached == 2
        assert len(validated_inventory.pages) == 3
        
        # Verify programmatic issues detected by Agent 02
        duplicate_titles = state.site_inventory.get("duplicate_titles", [])
        assert len(duplicate_titles) == 2, "Agent 02 should detect duplicate titles"
        
        print(f"  ✓ Agent 02 complete: {validated_inventory.total_pages} pages crawled")
        print(f"    - Duplicate titles: {len(duplicate_titles)}")
        print(f"    - Pages with schema: {validated_inventory.pages_with_schema}")
        
        # ========== STEP 3: Run Agent 03 (Technical Audit) ==========
        print("\n[STEP 3] Running Agent 03 (Technical Audit)...")
        
        await technical_agent.execute(state)
        
        # Assert - Agent 03 output
        assert state.technical_audit_report is not None, "Agent 03 should produce technical_audit_report"
        
        # Verify schema
        validated_report = TechnicalAuditReportSchema(**state.technical_audit_report)
        
        # Verify inference focus (Agent 03's main job)
        assert validated_report.total_inference_issues >= 0
        assert validated_report.overall_health_score > 0
        
        # Verify inference issues are categorized correctly
        if validated_report.inference_critical:
            for issue in validated_report.inference_critical:
                assert issue.issue_type in ["content_quality", "semantic_mismatch", "accessibility", "architecture"]
        
        # Verify programmatic summary exists (from Agent 02 data)
        prog_summary = validated_report.programmatic_summary
        assert prog_summary.duplicate_titles_count >= 0
        assert prog_summary.duplicate_meta_count >= 0
        
        print(f"  ✓ Agent 03 complete: health score {validated_report.overall_health_score}/100")
        print(f"    - Inference issues: {validated_report.total_inference_issues}")
        print(f"    - Critical: {len(validated_report.inference_critical)}")
        print(f"    - Warnings: {len(validated_report.inference_warnings)}")
        print(f"    - Programmatic issues (from Agent 02): {prog_summary.duplicate_titles_count} duplicate titles")
        
        # ========== STEP 4: Verify Data Flow ==========
        print("\n[STEP 4] Verifying data flow...")
        
        # Verify each agent's output is used by the next agent
        assert state.seo_project_context is not None  # Used by Agent 02
        assert state.site_inventory is not None  # Used by Agent 03
        assert state.technical_audit_report is not None  # Final output
        
        # Verify state status is updated
        assert state.status == "intelligence"
        
        print(f"  ✓ Data flows correctly through all agents")
        
        # ========== STEP 5: Verify LLM Call Count ==========
        print("\n[STEP 5] Verifying LLM call count...")
        
        # Should be 3 calls: one for each agent
        assert mock_gemini.call_count == 3, f"Expected 3 LLM calls, got {mock_gemini.call_count}"
        
        print(f"  ✓ Total LLM calls: {mock_gemini.call_count}")
        
        print("\n" + "="*60)
        print("✅ SEQUENTIAL TEST PASSED: Agent 01 → 02 → 03 works!")
        print("="*60)
    
    @pytest.mark.asyncio
    async def test_sequential_with_state_persistence(
        self,
        mock_gemini: MockGeminiClient,
        test_storage_dir: Path,
    ):
        """
        Sequential Test 2: Verify state persists correctly between agents
        
        Each agent should:
        1. Read input from previous agent's output
        2. Produce its own output
        3. Not modify previous agent's output
        """
        # Arrange
        state = SEOState(
            project_id="sequential_test_002",
            brand_id="brand_seq_002",
            website_url="https://acme-test.example.com",
            config={"crawl_depth": 1, "max_pages": 10},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        intake_agent = IntakeAgent(mock_gemini, "test-model", test_storage_dir)
        crawl_agent = CrawlAgent(mock_gemini, "test-model", test_storage_dir)
        technical_agent = TechnicalAuditAgent(mock_gemini, "test-model", test_storage_dir)
        
        # ========== Run All Three Agents ==========
        await intake_agent.execute(state)
        await crawl_agent.execute(state)
        await technical_agent.execute(state)
        
        # ========== Verify State Integrity ==========
        
        # Agent 01 output should not be modified by Agents 02/03
        assert state.seo_project_context["business_name"] == "Acme Corporation"
        assert state.seo_project_context["industry"] == "Technology"
        
        # Agent 02 output should not be modified by Agent 03
        # (Agent 03 should only read, not modify)
        assert state.site_inventory["total_pages"] == 10
        assert len(state.site_inventory["pages"]) == 3
        
        # Agent 03 output should exist
        assert state.technical_audit_report["total_inference_issues"] >= 0
        assert state.technical_audit_report["overall_health_score"] > 0
        
        print("\n✅ State persistence test PASSED!")
    
    @pytest.mark.asyncio
    async def test_sequential_error_handling(
        self,
        test_storage_dir: Path,
    ):
        """
        Sequential Test 3: Verify error handling when running out of order
        
        Agent 03 should fail if:
        - Agent 02 (site_inventory) has not been run
        - Agent 01 (seo_project_context) has not been run
        """
        # Test 1: Missing site_inventory
        print("\n[Test 3a] Testing error: missing site_inventory...")
        
        state_missing_inventory = SEOState(
            project_id="sequential_error_test",
            brand_id="brand_error",
            website_url="https://acme-test.example.com",
            seo_project_context={"business_name": "Test", "website_url": "https://test.com", "industry": "Tech"},
            # site_inventory is missing!
            config={},
        )
        
        mock_client = MockGeminiClient()
        technical_agent = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        try:
            await technical_agent.execute(state_missing_inventory)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "site_inventory required" in str(e)
            print("  ✓ Correctly blocked when site_inventory missing")
        
        # Test 2: Missing seo_project_context
        print("[Test 3b] Testing error: missing seo_project_context...")
        
        state_missing_context = SEOState(
            project_id="sequential_error_test_2",
            brand_id="brand_error_2",
            website_url="https://acme-test.example.com",
            site_inventory={"total_pages": 10, "pages": []},
            # seo_project_context is missing!
            config={},
        )
        
        technical_agent2 = TechnicalAuditAgent(mock_client, "test-model", test_storage_dir)
        
        try:
            await technical_agent2.execute(state_missing_context)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "seo_project_context required" in str(e)
            print("  ✓ Correctly blocked when seo_project_context missing")
        
        print("\n✅ Error handling test PASSED!")


# ================= MAIN =================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])