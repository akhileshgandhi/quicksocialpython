"""
TechnicalAuditAgent (Agent 03) — performs inference-based technical SEO audit.

IMPORTANT: Agent 02 (CrawlAgent) already performs programmatic detection of:
- Duplicate titles, duplicate meta descriptions, thin content pages
- Pages missing H1, meta descriptions, schema, OG tags
- Page status codes, response times, HTTPS check
- Broken links (4xx/5xx)

Agent 03 focuses EXCLUSIVELY on inference-based analysis using LLM:
- Content quality assessment (semantic value, not just word count)
- Semantic SEO analysis (title/content mismatch, keyword stuffing)
- Accessibility & UX signals (alt text quality, heading hierarchy)
- Architecture recommendations (orphaned pages, silo opportunities)

Input:
    state.site_inventory (from Agent 02) - the full page list with metadata
    state.seo_project_context (from Agent 01) - business context for inference
    
Output:
    TechnicalAuditReportSchema - inference-focused findings + programmatic summary

Dependencies:
    - Agent 02 must be complete (site_inventory required)
    - Agent 01 must be complete (seo_project_context required)
    
Gate Logic:
    - This agent triggers Gate 1 (gate1_technical)
    - After completion, the pipeline pauses for human approval
    - Cannot proceed to Agent 04 until gate is approved

Usage:
    agent = TechnicalAuditAgent(gemini_client, model, storage_dir)
    await agent.execute(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Type

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.constants import HEALTH_SCORE_WEIGHTS
from seo_agents.state import SEOState
from seo_agents.utils import normalize_list_field

if TYPE_CHECKING:
    from seo_agents.validators.schemas.technical_audit_report import TechnicalAuditReportSchema


class TechnicalAuditAgent(SEOBaseAgent):
    """Agent responsible for inference-based technical SEO audit."""
    
    agent_name: ClassVar[str] = "agent_03_technical"
    triggers_approval_gate: ClassVar[bool] = True

    def _validate_inputs(self, state: SEOState) -> None:
        """Validate required input fields exist before running the agent.
        
        Args:
            state: SEOState with site_inventory from Agent 02 and seo_project_context from Agent 01
            
        Raises:
            ValueError: If site_inventory or seo_project_context is missing
        """
        if not state.site_inventory:
            raise ValueError("site_inventory required (run Agent 02 first)")
        
        if not state.seo_project_context:
            raise ValueError("seo_project_context required (run Agent 01 first)")

    def _validate_outputs(self, state: SEOState) -> None:
        """Validate output was properly set by the agent.
        
        Args:
            state: SEOState that should contain technical_audit_report
            
        Raises:
            ValueError: If technical_audit_report is not set or fails schema validation
        """
        from seo_agents.validators.schemas.technical_audit_report import (
            TechnicalAuditReportSchema
        )
        
        if not state.technical_audit_report:
            raise ValueError("technical_audit_report was not set by TechnicalAuditAgent")
        
        TechnicalAuditReportSchema(**state.technical_audit_report)

    def _normalize_inference_issue(
        self, 
        issue: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize an inference issue to match the schema.
        
        Args:
            issue: Raw issue dictionary from LLM response
            
        Returns:
            Normalized issue dictionary ready for Pydantic validation
        """
        from seo_agents.validators.schemas.technical_audit_report import InferenceIssue
        
        normalized = issue.copy()
        
        # Ensure affected_urls is a list
        if "affected_urls" in normalized:
            urls = normalized["affected_urls"]
            if urls is None:
                normalized["affected_urls"] = []
            elif isinstance(urls, str):
                normalized["affected_urls"] = [urls]
            elif not isinstance(urls, list):
                normalized["affected_urls"] = []
        
        # Validate with Pydantic to ensure schema compliance
        return InferenceIssue(**normalized).model_dump()

    def _normalize_programmatic_summary(
        self, 
        summary: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize programmatic summary from Agent 02 data.
        
        Args:
            summary: Raw summary dictionary from LLM
            
        Returns:
            Normalized summary dictionary
        """
        from seo_agents.validators.schemas.technical_audit_report import ProgrammaticSummary
        
        if not summary:
            summary = {}
        
        # Use defaults for any missing fields
        summary.setdefault("duplicate_titles_count", 0)
        summary.setdefault("duplicate_meta_count", 0)
        summary.setdefault("thin_content_count", 0)
        summary.setdefault("pages_missing_h1_count", 0)
        summary.setdefault("pages_missing_meta_count", 0)
        summary.setdefault("broken_links_count", 0)
        
        return ProgrammaticSummary(**summary).model_dump()

    def _extract_programmatic_counts(
        self, 
        site_inventory: Dict[str, Any]
    ) -> Dict[str, int]:
        """Extract programmatic counts from site_inventory (Agent 02 output).
        
        Args:
            site_inventory: Site inventory from Agent 02
            
        Returns:
            Dictionary of programmatic counts
        """
        # Handle both dict and Pydantic model inputs
        if hasattr(site_inventory, 'model_dump'):
            # It's a Pydantic model, convert to dict
            inv_dict = site_inventory.model_dump()
        else:
            inv_dict = site_inventory
        
        duplicate_titles = inv_dict.get("duplicate_titles", [])
        duplicate_meta = inv_dict.get("duplicate_meta_descriptions", [])
        thin_content = inv_dict.get("thin_content_pages", [])
        
        total_pages = inv_dict.get("total_pages", 0)
        pages_with_h1 = inv_dict.get("pages_with_h1", 0)
        pages_with_meta = inv_dict.get("pages_with_meta_description", 0)
        
        # Count broken links from pages with 4xx/5xx status
        pages = inv_dict.get("pages", [])
        broken_links = 0
        for p in pages:
            # Handle both dict and Pydantic objects
            if hasattr(p, 'status_code'):
                status = p.status_code
            else:
                status = p.get("status_code", 200) if isinstance(p, dict) else 200
            if status >= 400:
                broken_links += 1
        
        return {
            "duplicate_titles_count": len(duplicate_titles) if duplicate_titles else 0,
            "duplicate_meta_count": len(duplicate_meta) if duplicate_meta else 0,
            "thin_content_count": len(thin_content) if thin_content else 0,
            "pages_missing_h1_count": total_pages - pages_with_h1 if pages_with_h1 is not None else 0,
            "pages_missing_meta_count": total_pages - pages_with_meta if pages_with_meta is not None else 0,
            "broken_links_count": broken_links,
        }

    def _calculate_health_score(
        self,
        inference_critical: List[Dict],
        inference_warnings: List[Dict],
        site_inventory: Dict[str, Any]
    ) -> int:
        """Calculate overall health score from inference issues + programmatic data.
        
        Args:
            inference_critical: List of critical inference issues
            inference_warnings: List of warning inference issues
            site_inventory: Site inventory for programmatic counts
            
        Returns:
            Health score 0-100
        """
        # Handle both dict and Pydantic model inputs
        if hasattr(site_inventory, 'model_dump'):
            inv_dict = site_inventory.model_dump()
        else:
            inv_dict = site_inventory
        
        # Get weights from constants
        w = HEALTH_SCORE_WEIGHTS
        max_d = {
            "inference_critical": 30,
            "inference_warnings": 20,
            "programmatic": 55,
        }
        
        # Start with perfect score
        score = 100
        
        # Deduct for critical issues
        critical_deduction = len(inference_critical) * w["critical_inference"]
        score -= min(critical_deduction, max_d["inference_critical"])
        
        # Deduct for warnings
        warning_deduction = len(inference_warnings) * w["warning_inference"]
        score -= min(warning_deduction, max_d["inference_warnings"])
        
        # Deduct for programmatic issues
        duplicate_titles = len(inv_dict.get("duplicate_titles", []))
        duplicate_meta = len(inv_dict.get("duplicate_meta_descriptions", []))
        thin_content = len(inv_dict.get("thin_content_pages", []))
        
        prog_deduction = (
            min(duplicate_titles * w["duplicate_title"], w["duplicate_title_max"]) +
            min(duplicate_meta * w["duplicate_meta"], w["duplicate_meta_max"]) +
            min(thin_content * w["thin_content"], w["thin_content_max"])
        )
        score -= min(prog_deduction, max_d["programmatic"])
        
        # Ensure score is within bounds
        return max(0, min(100, score))

    async def run(self, state: SEOState) -> None:
        """Execute the inference-based technical audit agent.
        
        Args:
            state: SEOState with site_inventory from Agent 02 and seo_project_context from Agent 01
            
        Returns:
            None - Results are stored in state.technical_audit_report
        """
        from seo_agents.prompts.technical import build_technical_audit_prompt
        from seo_agents.validators.schemas.technical_audit_report import (
            TechnicalAuditReportSchema
        )

        self.log("Starting inference-based technical audit")

        # Extract required data
        site_inventory = state.site_inventory
        seo_project_context = state.seo_project_context

        # Build prompt with both inventory and context
        prompt = build_technical_audit_prompt(site_inventory, seo_project_context)

        # Execute audit via LLM
        raw_report = await self._call_gemini(prompt=prompt)

        # Normalize inference issues
        normalized_critical = []
        normalized_warnings = []
        normalized_info = []

        for issue in raw_report.get("inference_critical", []):
            normalized_critical.append(self._normalize_inference_issue(issue))

        for issue in raw_report.get("inference_warnings", []):
            normalized_warnings.append(self._normalize_inference_issue(issue))

        for issue in raw_report.get("inference_info", []):
            normalized_info.append(self._normalize_inference_issue(issue))

        # Get programmatic summary from Agent 02 data
        programmatic_counts = self._extract_programmatic_counts(site_inventory)
        
        # Use LLM-provided summary if available, otherwise extract from inventory
        programmatic_summary = raw_report.get("programmatic_summary", {})
        if not programmatic_summary or programmatic_summary.get("duplicate_titles_count") is None:
            programmatic_summary = programmatic_counts
        else:
            # Merge with inventory counts for accuracy
            for key in programmatic_counts:
                if programmatic_summary.get(key) is None:
                    programmatic_summary[key] = programmatic_counts[key]

        # Normalize programmatic summary
        normalized_summary = self._normalize_programmatic_summary(programmatic_summary)

        # Calculate total inference issues
        total_inference_issues = (
            len(normalized_critical) + 
            len(normalized_warnings) + 
            len(normalized_info)
        )

        # Calculate health score
        health_score = raw_report.get("overall_health_score")
        if health_score is None:
            health_score = self._calculate_health_score(
                normalized_critical,
                normalized_warnings,
                site_inventory
            )

        # Build final normalized report with AEO/GEO fields
        # Normalize list fields for AEO/GEO recommendations
        aeo_recs = raw_report.get("aeo_recommendations")
        if aeo_recs is None:
            aeo_recs = []
        elif isinstance(aeo_recs, str):
            aeo_recs = [aeo_recs]
        
        geo_recs = raw_report.get("geo_recommendations")
        if geo_recs is None:
            geo_recs = []
        elif isinstance(geo_recs, str):
            geo_recs = [geo_recs]
        
        # Import enums for proper validation
        from seo_agents.validators.schemas.technical_audit_report import (
            VoiceSearchReadiness, SchemaQualityForAI
        )
        
        # Normalize enum fields
        voice_readiness_raw = raw_report.get("voice_search_readiness", "needs_improvement")
        try:
            voice_readiness = VoiceSearchReadiness(voice_readiness_raw)
        except ValueError:
            voice_readiness = VoiceSearchReadiness.NEEDS_IMPROVEMENT
        
        schema_quality_raw = raw_report.get("schema_quality_for_ai", "basic")
        try:
            schema_quality = SchemaQualityForAI(schema_quality_raw)
        except ValueError:
            schema_quality = SchemaQualityForAI.BASIC
        
        normalized_report = {
            "total_inference_issues": total_inference_issues,
            "inference_critical": normalized_critical,
            "inference_warnings": normalized_warnings,
            "inference_info": normalized_info,
            "programmatic_summary": normalized_summary,
            "overall_health_score": health_score,
            
            # AEO/GEO Enhancement fields
            "answer_readiness_score": raw_report.get("answer_readiness_score", 50),
            "citation_trust_score": raw_report.get("citation_trust_score", 50),
            "voice_search_readiness": voice_readiness,
            "aeo_recommendations": aeo_recs,
            "geo_recommendations": geo_recs,
            "schema_quality_for_ai": schema_quality,
        }

        # Validate against schema
        validated_report = TechnicalAuditReportSchema(**normalized_report)

        # Store in state
        state.technical_audit_report = validated_report.model_dump()
        state.status = "intelligence"

        # Get inventory as dict for logging (handle both formats)
        if hasattr(site_inventory, 'model_dump'):
            inv_dict = site_inventory.model_dump()
        else:
            inv_dict = site_inventory
        
        # Log summary (using consistent logging)
        self.log(f"Technical audit complete. Total inference issues: {total_inference_issues}")
        self.log(f"Critical: {len(normalized_critical)}, Warnings: {len(normalized_warnings)}")
        self.log(f"Health score: {health_score}/100")
        self.log(f"Programmatic issues: {normalized_summary}")

    def __all__(self) -> list[str]:
        return ["TechnicalAuditAgent", self.agent_name]