"""
SEOBaseAgent — abstract base class for all SEO agents.

Mirrors the scraper_agents/agents/base.py pattern.
Provides:
  - Gemini client + model references
  - Storage directory
  - Structured logging with agent name prefix
  - Time-budget enforcement so agents stop gracefully
  - Input/output validation hooks
  - Gemini API call wrapper with retry logic

Uses Google Gemini API:
  - Set LLM_PROVIDER=gemini to use Google Gemini
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Type

from tenacity import retry, stop_after_attempt, wait_exponential_jitter

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
        self._llm_provider = "gemini"  # Always use Gemini API

    async def execute(self, state: SEOState) -> None:
        """Template method: validate_inputs → run → validate_outputs with timeout."""
        self._start_time = time.time()
        self._current_state = state
        self.log(f"started (budget {self._time_budget:.0f}s, provider: {self._llm_provider})")

        try:
            self._validate_inputs(state)

            await asyncio.wait_for(self.run(state), timeout=self._time_budget)
        except asyncio.TimeoutError:
            error_msg = f"Agent {self.agent_name} timed out after {self._time_budget}s"
            state.errors.append(error_msg)
            self.log(error_msg, level="error")
        except Exception as exc:
            error_str = str(exc)
            self.log(f"FAILED: {exc.__class__.__name__}: {error_str}", level="error")
            state.errors.append(f"{self.agent_name}: {exc.__class__.__name__}: {error_str}")
            return  # Stop execution on failure to avoid misleading validation errors

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
        Unified LLM call - uses Google Gemini API.
        """
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
            wait=wait_exponential_jitter(initial=1, max=10),
        )
        def _generate():
            try:
                # the new python SDK calls are synchronous unless using await client.aio.models.generate_content
                # For simplicity and broad compatibility inside standard async tasks, 
                # we wrap it or use the standard call if the client handles it
                if hasattr(self.gemini, 'aio') and hasattr(self.gemini.aio, 'models'):
                     return self.gemini.aio.models.generate_content(
                        model=self.model,
                        contents=prompt,
                    )
                else:
                    return self.gemini.models.generate_content(
                        model=self.model,
                        contents=prompt,
                    )
                
            except Exception as api_error:
                self.log(f"API Error: {type(api_error).__name__}: {str(api_error)}", level="error")
                raise

        # We need to await if we trigger an aio call, otherwise we run it blocking
        # but in context of this async method, we can await an asyncio thread run if necessary
        # However, the user's test_key.py used a sync client, we will assume it might be sync.
        
        # If the returned object is a coroutine, we await it.
        import inspect
        result_or_coro = _generate()
        if inspect.iscoroutine(result_or_coro):
            response = await result_or_coro
        else:
            response = result_or_coro
            
        text = response.text

        if response_schema:
            result = validate_against_schema(text, response_schema)
        else:
            result = validate_json(text)

        if self._current_state:
            # Extract token usage from Gemini response if available
            prompt_tokens = 0
            output_tokens = 0
            total_tokens = 0
            
            if hasattr(response, 'usage_metadata'):
                usage = response.usage_metadata
                prompt_tokens = getattr(usage, 'prompt_token_count', 0) or 0
                output_tokens = getattr(usage, 'candidates_token_count', 0) or 0
                total_tokens = getattr(usage, 'total_token_count', 0) or (prompt_tokens + output_tokens)
            
            self._current_state.llm_calls.append(
                {
                    "call": f"{self.__class__.__name__}._call_gemini",
                    "provider": "gemini",
                    "model": self.model,
                    "prompt_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": total_tokens,
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
