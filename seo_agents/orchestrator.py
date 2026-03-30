"""
SEOOrchestrator — manages sequential execution of all 14 SEO agents,
handles gate pausing, state saving, and error recovery.
"""

from __future__ import annotations

import fcntl
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from seo_agents.agents.intake import IntakeAgent
from seo_agents.agents.crawl import CrawlAgent
from seo_agents.agents.technical import TechnicalAuditAgent
from seo_agents.agents.competitor import CompetitorAgent
from seo_agents.agents.keywords import KeywordResearchAgent
from seo_agents.agents.clustering import ClusteringAgent
from seo_agents.agents.page_mapping import PageMappingAgent
from seo_agents.agents.gap_analysis import GapAnalysisAgent
from seo_agents.agents.strategy import StrategyAgent
from seo_agents.agents.on_page import OnPageAgent
from seo_agents.agents.content_brief import ContentBriefAgent
from seo_agents.agents.content_writer import ContentWriterAgent
from seo_agents.agents.linking_schema import LinkingSchemaAgent
from seo_agents.agents.monitoring import MonitoringAgent
from seo_agents.base_agent import SEOBaseAgent
from seo_agents.constants import (
    GATE_BLOCK_MAP,
    GATE_TRIGGER_MAP,
    LAYER_AGENTS,
)
from seo_agents.state import SEOState, load_seo_state, save_seo_state

logger = logging.getLogger(__name__)

LOCK_FILE_MAX_AGE_SECONDS = 1800  # 30 minutes


class SEOOrchestrator:
    def __init__(
        self,
        gemini_client: Any,
        gemini_model: str,
        storage_dir: Path,
    ):
        self.gemini = gemini_client
        self.model = gemini_model
        self.storage_dir = storage_dir
        self._agents = self._initialize_agents()
        self._lock_file = None  # File handle for fcntl locking

    def _initialize_agents(self) -> List[SEOBaseAgent]:
        return [
            IntakeAgent(self.gemini, self.model, self.storage_dir),
            CrawlAgent(self.gemini, self.model, self.storage_dir),
            TechnicalAuditAgent(self.gemini, self.model, self.storage_dir),
            KeywordResearchAgent(self.gemini, self.model, self.storage_dir),
            ClusteringAgent(self.gemini, self.model, self.storage_dir),
            PageMappingAgent(self.gemini, self.model, self.storage_dir),
            CompetitorAgent(self.gemini, self.model, self.storage_dir),
            GapAnalysisAgent(self.gemini, self.model, self.storage_dir),
            StrategyAgent(self.gemini, self.model, self.storage_dir),
            OnPageAgent(self.gemini, self.model, self.storage_dir),
            ContentBriefAgent(self.gemini, self.model, self.storage_dir),
            ContentWriterAgent(self.gemini, self.model, self.storage_dir),
            LinkingSchemaAgent(self.gemini, self.model, self.storage_dir),
            MonitoringAgent(self.gemini, self.model, self.storage_dir),
        ]

    def _get_agent_by_name(self, agent_name: str) -> Optional[SEOBaseAgent]:
        for agent in self._agents:
            if agent.agent_name == agent_name:
                return agent
        return None

    def _gate_blocks_execution(self, agent: SEOBaseAgent, state: SEOState) -> bool:
        gate_name = GATE_BLOCK_MAP.get(agent.agent_name)
        if not gate_name:
            return False

        gate = state.approval_gates.get(gate_name, {})
        return gate.get("required", False) and not gate.get("approved", False)

    def _set_approval_gate(self, agent: SEOBaseAgent, state: SEOState) -> None:
        gate_name = GATE_TRIGGER_MAP.get(agent.agent_name)
        if gate_name and gate_name in state.approval_gates:
            state.approval_gates[gate_name]["required"] = True

    def _check_layer_complete(self, state: SEOState) -> None:
        current_layer = state.current_layer
        layer_agent_names = LAYER_AGENTS.get(current_layer, [])
        if all(name in state.completed_agents for name in layer_agent_names):
            if current_layer < 5:
                state.current_layer = current_layer + 1

    def _get_lock_path(self, project_id: str) -> Path:
        """Get path to the lock file for a project."""
        return self.storage_dir / "seo_projects" / project_id / ".lock"

    def _acquire_lock(self, project_id: str) -> bool:
        """Acquire lock for project using fcntl. Returns True if acquired, False if already locked."""
        lock_path = self._get_lock_path(project_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # Open lock file in append mode, create if doesn't exist
            self._lock_file = open(lock_path, 'a')
            # Try to acquire exclusive lock (non-blocking)
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write PID to file
            self._lock_file.write(f"{os.getpid()}\n")
            self._lock_file.flush()
            return True
        except (IOError, OSError):
            # Lock already held
            if self._lock_file:
                self._lock_file.close()
                self._lock_file = None
            return False

    def _release_lock(self, project_id: str) -> None:
        """Release lock for project."""
        try:
            if self._lock_file:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
                self._lock_file.close()
                self._lock_file = None
        except (IOError, OSError):
            pass

    def run(self, project_id: str) -> SEOState:
        """Run the full pipeline."""
        if not self._acquire_lock(project_id):
            raise RuntimeError(f"Pipeline already running for project {project_id}")
        
        try:
            state = load_seo_state(project_id, self.storage_dir)

            for agent in self._agents:
                if agent.agent_name in state.completed_agents:
                    continue

                if self._gate_blocks_execution(agent, state):
                    logger.info(f"Gate blocked execution for {agent.agent_name}")
                    break

                start_time = time.time()
                logger.info(f"Running agent: {agent.agent_name}")

                state.updated_at = datetime.now(timezone.utc)

                import asyncio

                asyncio.run(agent.execute(state))

                elapsed = time.time() - start_time
                state.completed_agents.append(agent.agent_name)

                self._check_layer_complete(state)

                save_seo_state(state, self.storage_dir)

                if agent.triggers_approval_gate:
                    self._set_approval_gate(agent, state)
                    save_seo_state(state, self.storage_dir)
                    logger.info(f"Gate triggered: {agent.agent_name} -> {GATE_TRIGGER_MAP.get(agent.agent_name)}")
                    break

            return state
        finally:
            self._release_lock(project_id)

    def run_single(self, project_id: str, agent_name: str) -> SEOState:
        """Run only the specified agent (used for re-runs)."""
        if not self._acquire_lock(project_id):
            raise RuntimeError(f"Pipeline already running for project {project_id}")
        
        try:
            state = load_seo_state(project_id, self.storage_dir)

            agent = self._get_agent_by_name(agent_name)
            if not agent:
                raise ValueError(f"Unknown agent: {agent_name}")

            if self._gate_blocks_execution(agent, state):
                raise ValueError(f"Gate blocking execution for {agent_name}")

            import asyncio

            asyncio.run(agent.execute(state))

            if agent.agent_name not in state.completed_agents:
                state.completed_agents.append(agent.agent_name)

            self._check_layer_complete(state)

            state.updated_at = datetime.now(timezone.utc)
            save_seo_state(state, self.storage_dir)

            if agent.triggers_approval_gate:
                self._set_approval_gate(agent, state)
                save_seo_state(state, self.storage_dir)

            return state
        finally:
            self._release_lock(project_id)

    def run_until_gate(self, project_id: str, gate_name: str) -> SEOState:
        """Run agents until the named gate is reached (used in integration tests)."""
        state = load_seo_state(project_id, self.storage_dir)

        for agent in self._agents:
            if agent.agent_name in state.completed_agents:
                continue

            if self._gate_blocks_execution(agent, state):
                break

            import asyncio

            asyncio.run(agent.execute(state))

            state.completed_agents.append(agent.agent_name)

            self._check_layer_complete(state)

            state.updated_at = datetime.now(timezone.utc)
            save_seo_state(state, self.storage_dir)

            triggered_gate = GATE_TRIGGER_MAP.get(agent.agent_name)
            if triggered_gate == gate_name:
                break

            if agent.triggers_approval_gate:
                self._set_approval_gate(agent, state)
                save_seo_state(state, self.storage_dir)
                break

        return state

    def approve_gate(self, project_id: str, gate_name: str, approved_by: str) -> SEOState:
        """Approve a gate and resume pipeline."""
        state = load_seo_state(project_id, self.storage_dir)

        if gate_name not in state.approval_gates:
            raise ValueError(f"Unknown gate: {gate_name}")

        gate = state.approval_gates[gate_name]
        if not gate.get("required"):
            raise ValueError(f"Gate {gate_name} has not been triggered yet")

        gate["approved"] = True
        gate["approved_by"] = approved_by
        gate["approved_at"] = datetime.now(timezone.utc).isoformat()

        save_seo_state(state, self.storage_dir)

        self.run(project_id)

        return state