"""
SEOBaseAgent — abstract base class for all SEO agents.

Mirrors the scraper_agents/agents/base.py pattern.
Provides:
  - Gemini client + model references
  - Storage directory
  - Structured logging with agent name prefix
  - Time-budget enforcement so agents stop gracefully
  - Input/output validation hooks
  - Gemini/Groq call wrapper with retry logic

Supports both Gemini and Groq APIs:
  - Set LLM_PROVIDER=groq to use Groq (for development)
  - Set LLM_PROVIDER=gemini (default) to use Google Gemini
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Type

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from seo_agents.state import SEOState

logger = logging.getLogger(__name__)


class SEOBaseAgent(ABC):
    """Every SEO agent subclasses this and implements ``async def run(state)``."""

    agent_name: str = "base"
    triggers_approval_gate: bool = False
    response_schema: Optional[Type] = None

    def __init__(
        self,
        gemini_client: Any,
        gemini_model: str,
        storage_dir: Path,
    ):
        from seo_agents.constants import SEO_TIME_BUDGETS

        self.gemini = gemini_client
        self.model = gemini_model
        self.storage_dir = storage_dir
        self._start_time: float = 0.0
        self._current_state: Optional[SEOState] = None
        self._time_budget: float = SEO_TIME_BUDGETS.get(self.agent_name, 60)
        
        # Detect LLM provider from environment
        self._llm_provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        self._groq_model = os.getenv("GROQ_MODEL", "qwen/qwen3-32b")

    async def execute(self, state: SEOState) -> None:
        """Template method: validate_inputs → run → validate_outputs with timeout."""
        self._start_time = time.time()
        self._current_state = state
        self.log(f"started (budget {self._time_budget:.0f}s, provider: {self._llm_provider})")

        self._validate_inputs(state)

        try:
            await asyncio.wait_for(self.run(state), timeout=self._time_budget)
        except asyncio.TimeoutError:
            error_msg = f"Agent {self.agent_name} timed out after {self._time_budget}s"
            state.errors.append(error_msg)
            self.log(error_msg, level="error")
        except Exception as exc:
            error_str = str(exc)
            self.log(f"FAILED: {exc.__class__.__name__}: {error_str}", level="error")
            state.errors.append(f"{self.agent_name}: {exc.__class__.__name__}: {error_str}")

        self._validate_outputs(state)

        elapsed = time.time() - self._start_time
        state.total_time_seconds += elapsed
        self.log(f"finished in {elapsed:.1f}s")

    @abstractmethod
    async def run(self, state: SEOState) -> None:
        """Agent-specific logic. Read from *state*, write results back."""
        ...

    def _validate_inputs(self, state: SEOState) -> None:
        """Override in subclasses to assert required input fields exist."""
        pass

    def _validate_outputs(self, state: SEOState) -> None:
        """Override in subclasses to validate output against Pydantic schema."""
        pass

    async def _call_gemini(
        self,
        prompt: str,
        response_schema: Optional[Type] = None,
    ) -> Dict[str, Any]:
        """
        Unified LLM call - routes to Gemini or Groq based on LLM_PROVIDER env var.
        """
        if self._llm_provider == "groq":
            return await self._call_groq(prompt, response_schema)
        return await self._call_gemini_native(prompt, response_schema)

    async def _call_gemini_native(
        self,
        prompt: str,
        response_schema: Optional[Type] = None,
    ) -> Dict[str, Any]:
        """Call Google Gemini API."""
        from seo_agents.validators.schemas import (
            validate_against_schema,
            validate_json,
        )

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
        )
        async def _generate():
            if hasattr(self.gemini, 'aio') and hasattr(self.gemini.aio, 'models'):
                response = await self.gemini.aio.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
            elif hasattr(self.gemini, 'models') and hasattr(self.gemini.models, 'generate_content'):
                response = await self.gemini.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
            else:
                response = await self.gemini.generate_content_async(
                    model=self.model,
                    contents=prompt,
                )
            
            text = response.text

            if response_schema:
                return validate_against_schema(text, response_schema)
            else:
                return validate_json(text)

        result = await _generate()

        if self._current_state:
            self._current_state.llm_calls.append(
                {
                    "call": f"{self.__class__.__name__}._call_gemini",
                    "provider": "gemini",
                    "model": self.model,
                    "prompt_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                }
            )

        return result

    async def _call_groq(
        self,
        prompt: str,
        response_schema: Optional[Type] = None,
    ) -> Dict[str, Any]:
        """Call Groq API (OpenAI-compatible)."""
        from seo_agents.validators.schemas import (
            validate_against_schema,
            validate_json,
        )

        groq_api_key = os.getenv("GROQ_API_KEY")
        if not groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is required when LLM_PROVIDER=groq")

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
        )
        async def _generate():
            async with httpx.AsyncClient() as client:
                try:
                    response = await client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={
                            "Authorization": f"Bearer {groq_api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self._groq_model,
                            "messages": [
                                {"role": "system", "content": "You are a helpful assistant. Return ONLY valid JSON, no markdown, no explanations."},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.3,
                            "max_tokens": 4096,
                        },
                        timeout=60.0,
                    )
                except httpx.TimeoutException:
                    raise ValueError("Groq API timeout")
                except httpx.ConnectError as e:
                    raise ValueError(f"Groq API connection error: {e}")
                
                # Handle rate limiting and other HTTP errors
                if response.status_code == 429:
                    raise ValueError("Rate limited - please try again later")
                if response.status_code >= 500:
                    raise ValueError(f"Groq API error: {response.status_code}")
                if response.status_code == 400:
                    error_body = response.text[:200]
                    raise ValueError(f"Groq API bad request: {error_body}")
                
                response.raise_for_status()
                result = response.json()
                text = result["choices"][0]["message"]["content"]

                if response_schema:
                    return validate_against_schema(text, response_schema)
                else:
                    return validate_json(text)

        result = await _generate()

        if self._current_state:
            self._current_state.llm_calls.append(
                {
                    "call": f"{self.__class__.__name__}._call_groq",
                    "provider": "groq",
                    "model": self._groq_model,
                    "prompt_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                }
            )

        return result

    def time_remaining(self) -> float:
        """Seconds left before the time budget expires."""
        return self._time_budget - (time.time() - self._start_time)

    def should_stop(self) -> bool:
        """True when less than 5s remain in the budget."""
        return self.time_remaining() < 5.0

    def log(self, msg: str, level: str = "info") -> None:
        tag = f"[{self.agent_name}]"
        getattr(logger, level, logger.info)(f"{tag} {msg}")
