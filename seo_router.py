"""
SEO Router — FastAPI endpoints for the SEO Agent system.

Provides endpoints for:
- Creating SEO projects
- Running the pipeline
- Managing approval gates
- Retrieving project status and data
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel

from seo_agents.orchestrator import SEOOrchestrator
from seo_agents.state import SEOState, save_seo_state, load_seo_state
from seo_agents.storage import load_data_object, list_jobs


# ================= REQUEST/RESPONSE MODELS =================

class SEOProjectCreate(BaseModel):
    """Request model for creating a new SEO project.
    
    Includes user-submitted form data as specified in the implementation plan.
    """
    # Identity
    brand_id: str
    website_url: str
    
    # Form data fields (as per plan line 409-411)
    business_name: Optional[str] = None
    industry: Optional[str] = None
    target_audience: Optional[list] = None
    primary_goals: Optional[list] = None
    competitors: Optional[list] = None
    brand_voice: Optional[str] = None
    key_products_services: Optional[list] = None
    
    # Configuration
    crawl_depth: int = 3
    target_geography: str = "Global"
    auto_approve: bool = False
    max_pages: int = 500


class SEOProjectResponse(BaseModel):
    """Response model for SEO project."""
    project_id: str
    brand_id: str
    website_url: str
    status: str
    current_layer: int
    completed_agents: list
    completed_agents_count: int
    approval_gates: dict
    created_at: Optional[str]
    updated_at: Optional[str]


class SEOStatusResponse(BaseModel):
    """Response model for project status."""
    project_id: str
    status: str
    current_layer: int
    completed_agents: list
    errors: list
    approval_gates: dict
    total_time_seconds: float


class PipelineStartResponse(BaseModel):
    """Response for pipeline start."""
    status: str
    project_id: str
    message: str


class GateApprovalRequest(BaseModel):
    """Request model for approving a gate."""
    approved_by: str


class GateApprovalResponse(BaseModel):
    """Response model for gate approval."""
    status: str
    gate: str
    approved_at: str


class DataObjectResponse(BaseModel):
    """Response model for data objects."""
    data: dict
    version: int


# ================= ROUTER FACTORY =================

def create_seo_router(gemini_client, gemini_model: str, storage_dir: Path) -> APIRouter:
    """Create and configure the SEO router."""
    
    # Initialize orchestrator
    orchestrator = SEOOrchestrator(
        gemini_client=gemini_client,
        gemini_model=gemini_model,
        storage_dir=storage_dir,
    )
    
    router = APIRouter(prefix="/api/seo", tags=["SEO"])
    
    # ================= PROJECT ENDPOINTS =================
    
    @router.post("/projects", response_model=SEOProjectResponse, status_code=status.HTTP_201_CREATED)
    async def create_project(
        project_data: SEOProjectCreate,
        storage_dir: Path = storage_dir,
    ):
        """Create a new SEO project.
        
        Accepts user-submitted form data and stores it for use by the intake agent.
        """
        project_id = str(uuid.uuid4())
        
        # Build intake form data from request
        intake_form_data = {}
        if project_data.business_name:
            intake_form_data["business_name"] = project_data.business_name
        if project_data.industry:
            intake_form_data["industry"] = project_data.industry
        if project_data.target_audience:
            intake_form_data["target_audience"] = project_data.target_audience
        if project_data.primary_goals:
            intake_form_data["primary_goals"] = project_data.primary_goals
        if project_data.competitors:
            intake_form_data["competitors"] = project_data.competitors
        if project_data.brand_voice:
            intake_form_data["brand_voice"] = project_data.brand_voice
        if project_data.key_products_services:
            intake_form_data["key_products_services"] = project_data.key_products_services
        
        state = SEOState(
            project_id=project_id,
            brand_id=project_data.brand_id,
            website_url=project_data.website_url,
            config={
                "crawl_depth": project_data.crawl_depth,
                "target_geography": project_data.target_geography,
                "auto_approve": project_data.auto_approve,
                "max_pages": project_data.max_pages,
            },
            status="discovery",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        
        # Store intake form data in config for the agent to use
        state.config["intake_form_data"] = intake_form_data
        
        save_seo_state(state, storage_dir)
        
        return SEOProjectResponse(
            project_id=project_id,
            brand_id=state.brand_id,
            website_url=state.website_url,
            status=state.status,
            current_layer=state.current_layer,
            completed_agents=state.completed_agents,
            completed_agents_count=len(state.completed_agents),
            approval_gates=state.approval_gates,
            created_at=state.created_at.isoformat() if state.created_at else None,
            updated_at=state.updated_at.isoformat() if state.updated_at else None,
        )
    
    
    @router.get("/projects/{project_id}", response_model=SEOProjectResponse)
    async def get_project(project_id: str, storage_dir: Path = storage_dir):
        """Get project details."""
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        return SEOProjectResponse(
            project_id=state.project_id,
            brand_id=state.brand_id or "",
            website_url=state.website_url,
            status=state.status,
            current_layer=state.current_layer,
            completed_agents=state.completed_agents,
            completed_agents_count=len(state.completed_agents),
            approval_gates=state.approval_gates,
            created_at=state.created_at.isoformat() if state.created_at else None,
            updated_at=state.updated_at.isoformat() if state.updated_at else None,
        )
    
    
    @router.get("/projects")
    async def list_projects(storage_dir: Path = storage_dir):
        """List all SEO projects."""
        projects_dir = storage_dir / "seo_projects"
        
        if not projects_dir.exists():
            return {"projects": []}
        
        projects = []
        for project_path in projects_dir.iterdir():
            if project_path.is_dir() and (project_path / "project.json").exists():
                try:
                    state = load_seo_state(project_path.name, storage_dir)
                    projects.append({
                        "project_id": state.project_id,
                        "brand_id": state.brand_id,
                        "website_url": state.website_url,
                        "status": state.status,
                        "current_layer": state.current_layer,
                        "completed_agents_count": len(state.completed_agents),
                    })
                except Exception:
                    continue
        
        return {"projects": projects}
    
    
    @router.post("/projects/{project_id}/run", response_model=PipelineStartResponse)
    async def run_pipeline(
        project_id: str,
        background_tasks: BackgroundTasks,
        storage_dir: Path = storage_dir,
    ):
        """Start the SEO pipeline for a project."""
        # Check project exists
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        # Check if pipeline already running by checking lock file
        lock_path = storage_dir / "seo_projects" / project_id / ".lock"
        if lock_path.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Pipeline already running for project {project_id}"
            )
        
        # Run pipeline in background
        background_tasks.add_task(orchestrator.run, project_id)
        
        return PipelineStartResponse(
            status="started",
            project_id=project_id,
            message="Pipeline started in background"
        )
    
    
    @router.post("/projects/{project_id}/run-agent/{agent_name}")
    async def run_single_agent(
        project_id: str,
        agent_name: str,
        storage_dir: Path = storage_dir,
    ):
        """Run a single agent for a project."""
        # Check project exists
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        # Validate agent name
        from seo_agents.constants import ALL_AGENTS
        if agent_name not in ALL_AGENTS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown agent: {agent_name}"
            )
        
        # Check lock
        lock_path = storage_dir / "seo_projects" / project_id / ".lock"
        if lock_path.exists():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Pipeline already running for project {project_id}"
            )
        
        try:
            state = orchestrator.run_single(project_id, agent_name)
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e)
            )
        
        return {
            "status": "completed",
            "project_id": project_id,
            "agent": agent_name,
            "completed_agents": state.completed_agents,
        }
    
    
    @router.get("/projects/{project_id}/status", response_model=SEOStatusResponse)
    async def get_status(project_id: str, storage_dir: Path = storage_dir):
        """Get project status (lightweight, no computation)."""
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        return SEOStatusResponse(
            project_id=state.project_id,
            status=state.status,
            current_layer=state.current_layer,
            completed_agents=state.completed_agents,
            errors=state.errors,
            approval_gates=state.approval_gates,
            total_time_seconds=state.total_time_seconds,
        )
    
    
    @router.post("/projects/{project_id}/approve-gate/{gate_name}", response_model=GateApprovalResponse)
    async def approve_gate(
        project_id: str,
        gate_name: str,
        approval: GateApprovalRequest,
        storage_dir: Path = storage_dir,
    ):
        """Approve an approval gate and resume pipeline."""
        from seo_agents.constants import GATE_NAMES
        
        # Validate gate name
        if gate_name not in GATE_NAMES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown gate: {gate_name}"
            )
        
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        gate = state.approval_gates.get(gate_name)
        if not gate or not gate.get("required"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Gate {gate_name} has not been triggered yet"
            )
        
        # Approve the gate
        state.approval_gates[gate_name]["approved"] = True
        state.approval_gates[gate_name]["approved_by"] = approval.approved_by
        state.approval_gates[gate_name]["approved_at"] = datetime.utcnow().isoformat()
        
        save_seo_state(state, storage_dir)
        
        # Resume pipeline in background
        import asyncio
        asyncio.create_task(orchestrator.run(project_id))
        
        return GateApprovalResponse(
            status="approved",
            gate=gate_name,
            approved_at=state.approval_gates[gate_name]["approved_at"],
        )
    
    
    @router.get("/projects/{project_id}/data/{data_type}", response_model=DataObjectResponse)
    async def get_data_object(
        project_id: str,
        data_type: str,
        version: Optional[int] = None,
        storage_dir: Path = storage_dir,
    ):
        """Get a data object for a project."""
        from seo_agents.constants import SEO_DATA_TYPES
        
        if data_type not in SEO_DATA_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown data type: {data_type}"
            )
        
        data = load_data_object(project_id, data_type, version, storage_dir)
        
        if data is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No data found for type {data_type}"
            )
        
        # Determine version
        if version is None:
            from seo_agents.storage import list_data_object_versions
            versions = list_data_object_versions(project_id, data_type, storage_dir)
            version = max(versions) if versions else 1
        
        return DataObjectResponse(data=data, version=version)
    
    
    @router.get("/projects/{project_id}/jobs")
    async def list_project_jobs(project_id: str, storage_dir: Path = storage_dir):
        """List all jobs for a project."""
        # Check project exists
        project_dir = storage_dir / "seo_projects" / project_id
        if not project_dir.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        jobs = list_jobs(project_id, storage_dir)
        return {"jobs": jobs}
    
    
    @router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def archive_project(project_id: str, storage_dir: Path = storage_dir):
        """Archive a project (sets status to archived, does not delete files)."""
        try:
            state = load_seo_state(project_id, storage_dir)
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Project {project_id} not found"
            )
        
        state.status = "archived"
        state.updated_at = datetime.utcnow()
        
        save_seo_state(state, storage_dir)
        
        return None
    
    return router