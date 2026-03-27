"""
SEOState — shared mutable state across all SEO agents for a single project.

Each agent reads fields written by earlier agents and writes its own output
fields. Mirrors the scraper_agents/state.py pattern.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SEOState:
    # ── Identity (set by Orchestrator before any agent runs) ─────────────────
    project_id: str = ""
    brand_id: Optional[str] = None
    website_url: str = ""

    # ── Layer 1: Discovery & Intelligence ──────────────────────────────────
    seo_project_context: Optional[Dict[str, Any]] = None
    site_inventory: Optional[Dict[str, Any]] = None
    technical_audit_report: Optional[Dict[str, Any]] = None
    competitor_matrix: Optional[Dict[str, Any]] = None
    keyword_universe: Optional[Dict[str, Any]] = None

    # ── Layer 2: Keyword & Page Analysis ────────────────────────────────────
    keyword_clusters: Optional[Dict[str, Any]] = None
    page_keyword_map: Optional[Dict[str, Any]] = None
    content_gap_report: Optional[Dict[str, Any]] = None

    # ── Layer 3: Strategy ───────────────────────────────────────────────────
    seo_priority_backlog: Optional[Dict[str, Any]] = None

    # ── Layer 4: Execution ───────────────────────────────────────────────────
    page_optimization_briefs: Optional[Dict[str, Any]] = None
    content_briefs: Optional[Dict[str, Any]] = None
    content_drafts: Optional[Dict[str, Any]] = None
    internal_link_graph: Optional[Dict[str, Any]] = None
    schema_map: Optional[Dict[str, Any]] = None

    # ── Layer 5: Monitoring ─────────────────────────────────────────────────
    performance_dashboard: Optional[Dict[str, Any]] = None
    reoptimization_queue: Optional[Dict[str, Any]] = None

    # ── Pipeline Metadata ────────────────────────────────────────────────────
    completed_agents: List[str] = field(default_factory=list)
    current_layer: int = 1
    status: str = "discovery"
    errors: List[str] = field(default_factory=list)
    total_time_seconds: float = 0.0

    # ── Approval Gates ───────────────────────────────────────────────────────
    approval_gates: Dict[str, Dict[str, Any]] = field(default_factory=lambda: {
        "gate1_technical": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
        "gate2_strategy": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
        "gate3_content": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
        "gate4_reoptimization": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
    })

    # ── Configuration ────────────────────────────────────────────────────────
    config: Dict[str, Any] = field(default_factory=lambda: {
        "crawl_depth": 3,
        "target_geography": "Global",
        "auto_approve": False,
        "max_pages": 500,
    })

    # ── LLM Usage Tracking ───────────────────────────────────────────────────
    llm_calls: List[Dict[str, Any]] = field(default_factory=list)

    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        """Initialize timestamps if not set."""
        now = datetime.utcnow()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now


def save_seo_state(state: SEOState, storage_dir: Path) -> None:
    """Serialize SEOState to JSON file with atomic write."""
    project_dir = storage_dir / "seo_projects" / state.project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    temp_path = project_dir / "project.json.tmp"
    target_path = project_dir / "project.json"

    state_dict = {
        "project_id": state.project_id,
        "brand_id": state.brand_id,
        "website_url": state.website_url,
        "seo_project_context": state.seo_project_context,
        "site_inventory": state.site_inventory,
        "technical_audit_report": state.technical_audit_report,
        "competitor_matrix": state.competitor_matrix,
        "keyword_universe": state.keyword_universe,
        "keyword_clusters": state.keyword_clusters,
        "page_keyword_map": state.page_keyword_map,
        "content_gap_report": state.content_gap_report,
        "seo_priority_backlog": state.seo_priority_backlog,
        "page_optimization_briefs": state.page_optimization_briefs,
        "content_briefs": state.content_briefs,
        "content_drafts": state.content_drafts,
        "internal_link_graph": state.internal_link_graph,
        "schema_map": state.schema_map,
        "performance_dashboard": state.performance_dashboard,
        "reoptimization_queue": state.reoptimization_queue,
        "completed_agents": state.completed_agents,
        "current_layer": state.current_layer,
        "status": state.status,
        "errors": state.errors,
        "total_time_seconds": state.total_time_seconds,
        "approval_gates": state.approval_gates,
        "config": state.config,
        "created_at": state.created_at.isoformat() if state.created_at else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else datetime.utcnow().isoformat(),
    }

    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, indent=2)

    os.replace(temp_path, target_path)


def load_seo_state(project_id: str, storage_dir: Path) -> SEOState:
    """Deserialize JSON file to SEOState instance."""
    project_dir = storage_dir / "seo_projects" / project_id
    target_path = project_dir / "project.json"

    if not target_path.exists():
        raise FileNotFoundError(f"Project file not found: {target_path}")

    with open(target_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    def parse_datetime(val: Optional[str]) -> Optional[datetime]:
        if val is None:
            return None
        try:
            return datetime.fromisoformat(val)
        except ValueError:
            return None

    return SEOState(
        project_id=data.get("project_id", ""),
        brand_id=data.get("brand_id"),
        website_url=data.get("website_url", ""),
        seo_project_context=data.get("seo_project_context"),
        site_inventory=data.get("site_inventory"),
        technical_audit_report=data.get("technical_audit_report"),
        competitor_matrix=data.get("competitor_matrix"),
        keyword_universe=data.get("keyword_universe"),
        keyword_clusters=data.get("keyword_clusters"),
        page_keyword_map=data.get("page_keyword_map"),
        content_gap_report=data.get("content_gap_report"),
        seo_priority_backlog=data.get("seo_priority_backlog"),
        page_optimization_briefs=data.get("page_optimization_briefs"),
        content_briefs=data.get("content_briefs"),
        content_drafts=data.get("content_drafts"),
        internal_link_graph=data.get("internal_link_graph"),
        schema_map=data.get("schema_map"),
        performance_dashboard=data.get("performance_dashboard"),
        reoptimization_queue=data.get("reoptimization_queue"),
        completed_agents=data.get("completed_agents", []),
        current_layer=data.get("current_layer", 1),
        status=data.get("status", "discovery"),
        errors=data.get("errors", []),
        total_time_seconds=data.get("total_time_seconds", 0.0),
        approval_gates=data.get("approval_gates", {
            "gate1_technical": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
            "gate2_strategy": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
            "gate3_content": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
            "gate4_reoptimization": {"required": False, "approved": False, "approved_by": None, "approved_at": None},
        }),
        config=data.get("config", {"crawl_depth": 3, "target_geography": "Global", "auto_approve": False, "max_pages": 500}),
        created_at=parse_datetime(data.get("created_at")),
        updated_at=parse_datetime(data.get("updated_at")),
    )