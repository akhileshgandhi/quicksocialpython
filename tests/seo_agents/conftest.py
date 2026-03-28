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
from datetime import datetime
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
    
    async def generate_content_async(self, model: str, contents: str) -> MockGeminiResponse:
        """Mock the Gemini generate_content_async method."""
        self._call_count += 1
        
        # Log the call
        self._call_log.append({
            "call_number": self._call_count,
            "model": model,
            "prompt_length": len(contents),
            "prompt_preview": contents[:100] + "..." if len(contents) > 100 else contents,
        })
        
        # Raise exception if configured
        if self._raise_on_call:
            exc = self._raise_on_call
            self._raise_on_call = None
            raise exc
        
        # Check for prompt-specific responses
        for prompt_key, response in self._responses_by_prompt.items():
            if prompt_key in contents:
                return MockGeminiResponse(text=response)
        
        # Return from sequential responses if available
        if self._responses:
            if self._response_index < len(self._responses):
                response = self._responses[self._response_index]
                self._response_index += 1
                return MockGeminiResponse(text=response)
        
        # Return default response
        if self._default_response:
            return MockGeminiResponse(text=self._default_response)
        
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
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
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
            {"url": "https://example.com/", "status_code": 200, "title": "Home", "meta_description": "Welcome", "h1": "Example Corp", "word_count": 500},
            {"url": "https://example.com/about", "status_code": 200, "title": "About Us", "meta_description": "About", "h1": "About", "word_count": 300},
            {"url": "https://example.com/products", "status_code": 200, "title": "Products", "meta_description": "Our Products", "h1": "Products", "word_count": 800},
        ],
        "crawl_errors": [],
    })
