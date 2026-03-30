"""
Shared test fixtures for SEO agent tests.

Fixtures:
- mock_gemini_client: Mock Gemini client with configurable responses
- tmp_storage_dir: Temporary directory for each test
- sample_seo_state: Pre-populated SEOState with realistic data
- orchestrator: SEOOrchestrator with mocked dependencies
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from seo_agents.state import SEOState
from seo_agents.orchestrator import SEOOrchestrator


class MockGeminiResponse:
    """Mock response object mimicking Gemini API response."""
    
    def __init__(self, text: str):
        self.text = text


class MockModels:
    def __init__(self, parent: MockGeminiClient):
        self.parent = parent
        
    def generate_content(self, model: str = None, contents: str = None, **kwargs) -> MockGeminiResponse:
        """Mock the Gemini generate_content method."""
        # Handle both positional and keyword arguments
        if contents is None and len(kwargs.get('contents', '')) > 0:
            contents = kwargs.get('contents', '')
        if model is None:
            model = kwargs.get('model', 'test-model')
            
        self.parent._call_count += 1
        
        # Log the call
        self.parent._call_log.append({
            "call_number": self.parent._call_count,
            "model": model,
            "prompt_length": len(contents) if contents else 0,
            "prompt_preview": (contents[:100] + "...") if contents and len(contents) > 100 else (contents or ""),
        })
        
        # Raise exception if configured
        if self.parent._raise_on_call:
            exc = self.parent._raise_on_call
            self.parent._raise_on_call = None
            raise exc
        
        # Check for prompt-specific responses
        if contents:
            for prompt_key, response in self.parent._responses_by_prompt.items():
                if prompt_key in contents:
                    return MockGeminiResponse(text=response)
            
            # Return from sequential responses if available
            if self.parent._responses:
                if self.parent._response_index < len(self.parent._responses):
                    response = self.parent._responses[self.parent._response_index]
                    self.parent._response_index += 1
                    return MockGeminiResponse(text=response)
        
        # Return default response
        if self.parent._default_response:
            return MockGeminiResponse(text=self.parent._default_response)
        
        # Return a default valid response
        return MockGeminiResponse(text=json.dumps({
            "business_name": "Test Company",
            "website_url": "https://example.com",
            "industry": "Technology",
            "target_audience": ["Businesses", "Developers"],
            "primary_goals": ["Increase traffic", "Generate leads"],
            "geographic_focus": "Global",
            "competitors": ["competitor1.com", "competitor2.com"],
            "brand_voice": "Professional and technical",
            "key_products_services": ["Software", "Consulting"],
        }))

class MockAioModels:
    """Mock async models for Gemini aio client."""
    def __init__(self, parent: MockGeminiClient):
        self.parent = parent
        self._sync_models = MockModels(parent)
    
    def generate_content(self, model: str = None, contents: str = None, **kwargs):
        """Return a coroutine that resolves to the sync response."""
        async def async_wrapper():
            return self._sync_models.generate_content(model, contents, **kwargs)
        return async_wrapper()


class MockGeminiClient:
    """Mock Gemini client that returns configurable responses."""
    
    def __init__(self):
        self._responses: list = []
        self._response_index = 0
        self._call_count = 0
        self._responses_by_prompt: Dict[str, str] = {}
        self._default_response: Optional[str] = None
        self._raise_on_call: Optional[Exception] = None
        self._call_log: List[Dict[str, Any]] = []
        self.models = MockModels(self)
        self.aio = MockAioModels(self)
    
    def set_response(self, response: str) -> None:
        """Set a single response for all calls."""
        self._default_response = response
    
    def set_responses(self, responses: List[str]) -> None:
        """Set multiple responses to be returned in sequence."""
        self._responses = responses
        self._response_index = 0
    
    def set_response_for_prompt(self, prompt_contains: str, response: str) -> None:
        """Set a specific response for prompts containing certain text."""
        self._responses_by_prompt[prompt_contains] = response
    
    def set_raise_on_call(self, exception: Exception) -> None:
        """Configure the client to raise an exception on the next call."""
        self._raise_on_call = exception
    
    @property
    def call_count(self) -> int:
        return self._call_count
    
    @property
    def call_log(self) -> List[Dict[str, Any]]:
        return self._call_log.copy()


# ================= FIXTURES =================

@pytest.fixture
def mock_gemini_client() -> MockGeminiClient:
    """Create a fresh mock Gemini client for each test."""
    return MockGeminiClient()


@pytest.fixture
def tmp_storage_dir(tmp_path: Path) -> Path:
    """Create a temporary storage directory for each test."""
    storage_dir = tmp_path / "test_storage"
    storage_dir.mkdir(exist_ok=True)
    return storage_dir


@pytest.fixture
def sample_seo_state(tmp_storage_dir: Path) -> SEOState:
    """Create a pre-populated SEOState with realistic Layer 1 data."""
    state = SEOState(
        project_id="test_001",
        brand_id="brand_001",
        website_url="https://example.com",
        config={
            "crawl_depth": 3,
            "target_geography": "United States",
            "auto_approve": False,
            "max_pages": 100,
            "intake_form_data": {
                "business_name": "Example Corp",
                "industry": "SaaS",
                "target_audience": ["SMBs", "Marketing teams"],
                "primary_goals": ["Increase traffic", "Generate leads"],
                "competitors": ["competitor-a.com", "competitor-b.com"],
                "brand_voice": "Professional, helpful",
                "key_products_services": ["Marketing Automation", "Analytics Dashboard"],
            },
        },
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return state


@pytest.fixture
def sample_state_with_project_context(sample_seo_state: SEOState) -> SEOState:
    """State with Agent 01 output populated."""
    state = sample_seo_state
    state.seo_project_context = {
        "business_name": "Example Corp",
        "website_url": "https://example.com",
        "industry": "SaaS",
        "target_audience": ["SMBs", "Marketing teams", "E-commerce businesses"],
        "primary_goals": ["Increase organic traffic", "Generate qualified leads"],
        "geographic_focus": "United States",
        "competitors": ["competitor-a.com", "competitor-b.com"],
        "brand_voice": "Professional, helpful, data-driven",
        "key_products_services": ["Marketing Automation", "Analytics Dashboard", "Email Campaigns"],
    }
    state.completed_agents = ["agent_01_intake"]
    state.current_layer = 1
    return state


@pytest.fixture
def orchestrator(mock_gemini_client: MockGeminiClient, tmp_storage_dir: Path) -> SEOOrchestrator:
    """Create an SEOOrchestrator with mocked dependencies."""
    return SEOOrchestrator(
        gemini_client=mock_gemini_client,
        gemini_model="test-model",
        storage_dir=tmp_storage_dir,
    )


# ================= HELPER FUNCTIONS =================

def get_mock_intake_response() -> str:
    """Return a realistic mock response for Agent 01 Intake."""
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


def get_mock_crawl_response() -> str:
    """Return a realistic mock response for Agent 02 Crawl."""
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


def get_mock_keyword_response() -> str:
    """Return a realistic mock response for Agent 05 Keyword Research with AEO/GEO fields."""
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
