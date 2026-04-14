"""
BaseAgent — abstract base class for all scraper agents.

Provides:
  - Gemini client + model references
  - Storage directory
  - Structured logging with agent name prefix
  - Time-budget enforcement so agents stop gracefully
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Sequence

from scraper_agents.config import AGENT_TIME_BUDGETS
from scraper_agents.state import ScrapeState

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Every agent subclasses this and implements ``async def run(state)``."""

    # Subclasses override to match a key in AGENT_TIME_BUDGETS
    agent_name: str = "base"

    def __init__(
        self,
        gemini_client: Any,
        gemini_model: str,
        storage_dir: Path,
        *,
        text_models: Optional[Sequence[str]] = None,
    ):
        self.gemini = gemini_client
        self.model = gemini_model
        self.text_models: tuple[str, ...] = (
            tuple(text_models) if text_models else (gemini_model,)
        )
        self.storage_dir = storage_dir
        self._start_time: float = 0.0
        self._time_budget: float = AGENT_TIME_BUDGETS.get(self.agent_name, 60)

    # ── public entry point ────────────────────────────────────────────────
    async def execute(self, state: ScrapeState) -> None:
        """Wraps ``run()`` with timing, logging, and error handling."""
        self._start_time = time.time()
        self.log(f"started (budget {self._time_budget:.0f}s)")
        try:
            await self.run(state)
        except Exception as exc:
            self.log(f"FAILED: {exc.__class__.__name__}: {exc}", level="error")
        elapsed = time.time() - self._start_time
        self.log(f"finished in {elapsed:.1f}s")

    @abstractmethod
    async def run(self, state: ScrapeState) -> None:
        """Agent-specific logic.  Read from *state*, write results back."""
        ...

    # ── helpers ───────────────────────────────────────────────────────────
    def time_remaining(self) -> float:
        """Seconds left before the time budget expires."""
        return self._time_budget - (time.time() - self._start_time)

    def should_stop(self) -> bool:
        """True when less than 5 s remain in the budget."""
        return self.time_remaining() < 5.0

    def log(self, msg: str, level: str = "info") -> None:
        tag = f"[{self.__class__.__name__}]"
        getattr(logger, level, logger.info)(f"{tag} {msg}")
