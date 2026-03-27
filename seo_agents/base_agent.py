"""
SEOBaseAgent — abstract base class for all SEO agents.

Mirrors the scraper_agents/agents/base.py pattern.
Provides:
  - Gemini client + model references
  - Storage directory
  - Structured logging with agent name prefix
  - Time-budget enforcement so agents stop gracefully
  - Input/output validation hooks
  - Gemini call wrapper with retry logic
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional, Type

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

    async def execute(self, state: SEOState) -> None:
        """Template method: validate_inputs → run → validate_outputs with timeout."""
        self._start_time = time.time()
        self._current_state = state  # Store for llm_calls tracking
        self.log(f"started (budget {self._time_budget:.0f}s)")

        self._validate_inputs(state)

        try:
            await asyncio.wait_for(self.run(state), timeout=self._time_budget)
        except asyncio.TimeoutError:
            error_msg = f"Agent {self.agent_name} timed out after {self._time_budget}s"
            state.errors.append(error_msg)
            self.log(error_msg, level="error")
        except Exception as exc:
            self.log(f"FAILED: {exc.__class__.__name__}: {exc}", level="error")
            state.errors.append(f"{self.agent_name}: {exc.__class__.__name__}: {exc}")

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
        """Call Gemini with retry logic, parse JSON, validate against schema."""
        from seo_agents.validators.schemas import (
            validate_against_schema,
        )

        @retry(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=1, min=1, max=10),
        )
        async def _generate():
            response = await self.gemini.generate_content_async(
                model=self.model,
                contents=prompt,
            )
            text = response.text

            if response_schema:
                return validate_against_schema(text, response_schema)
            else:
                from seo_agents.validators.schemas import validate_json
                return validate_json(text)

        result = await _generate()

        if self._current_state:
            self._current_state.llm_calls.append(
                {
                    "call": f"{self.__class__.__name__}._call_gemini",
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