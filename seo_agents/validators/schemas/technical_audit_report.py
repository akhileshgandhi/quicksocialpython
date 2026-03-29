"""Pydantic schema for technical audit report - Agent 03.

This schema defines the structure for inference-based technical SEO analysis.
Agent 02 already handles programmatic detection (duplicate titles, missing meta, etc.)
Agent 03 focuses exclusively on inference-based analysis using LLM inference.

Input:
    state.site_inventory (from Agent 02) - full page list with metadata
    state.seo_project_context (from Agent 01) - business context for inference

Output:
    TechnicalAuditReportSchema - inference-focused findings + programmatic summary

Inference Categories:
    - content_quality: Content quality assessment via LLM
    - semantic_mismatch: Title/meta vs content mismatch
    - accessibility: Image alt text quality, heading hierarchy
    - architecture: Internal link structure, orphaned pages

Exports:
    All schema classes and enums
"""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class VoiceSearchReadiness(str, Enum):
    """Enum for voice search readiness levels."""
    EXCELLENT = "excellent"
    GOOD = "good"
    NEEDS_IMPROVEMENT = "needs_improvement"
    POOR = "poor"


class SchemaQualityForAI(str, Enum):
    """Enum for schema quality for AI citation."""
    NONE = "none"
    BASIC = "basic"
    GOOD = "good"
    EXCELLENT = "excellent"


class InferenceIssue(BaseModel):
    """An issue detected via LLM inference (not programmatic detection)."""
    
    issue_type: str = Field(
        description="Type of inference issue: content_quality, semantic_mismatch, accessibility, architecture"
    )
    severity: str = Field(
        description="Severity level: critical, warning, info"
    )
    affected_urls: List[str] = Field(
        default_factory=list,
        description="List of URLs affected by this issue"
    )
    description: str = Field(
        description="LLM-generated description of the issue"
    )
    recommendation: str = Field(
        description="Actionable recommendation to fix this issue"
    )


class ProgrammaticSummary(BaseModel):
    """Summary of programmatic issues detected by Agent 02.
    
    These are included for reference in Agent 03's report to give
    a complete picture of technical SEO health.
    """
    
    duplicate_titles_count: int = Field(
        default=0,
        description="Number of duplicate title tags (from Agent 02)"
    )
    duplicate_meta_count: int = Field(
        default=0,
        description="Number of duplicate meta descriptions (from Agent 02)"
    )
    thin_content_count: int = Field(
        default=0,
        description="Number of thin content pages (from Agent 02)"
    )
    pages_missing_h1_count: int = Field(
        default=0,
        description="Number of pages missing H1 tags (from Agent 02)"
    )
    pages_missing_meta_count: int = Field(
        default=0,
        description="Number of pages missing meta descriptions (from Agent 02)"
    )
    broken_links_count: int = Field(
        default=0,
        description="Number of broken internal links (4xx/5xx) from Agent 02"
    )


class TechnicalAuditReportSchema(BaseModel):
    """Complete technical audit report combining inference analysis + programmatic summary.
    
    Enhanced with AEO/GEO fields for Answer Engine Optimization and Generative Engine Optimization.
    """
    
    total_inference_issues: int = Field(
        description="Total number of inference-based issues found"
    )
    inference_critical: List[InferenceIssue] = Field(
        default_factory=list,
        description="Critical inference issues requiring immediate attention"
    )
    inference_warnings: List[InferenceIssue] = Field(
        default_factory=list,
        description="Warning-level inference issues"
    )
    inference_info: List[InferenceIssue] = Field(
        default_factory=list,
        description="Informational inference issues"
    )
    programmatic_summary: ProgrammaticSummary = Field(
        default_factory=ProgrammaticSummary,
        description="Summary of programmatic issues from Agent 02"
    )
    overall_health_score: int = Field(
        ge=0,
        le=100,
        description="Combined health score (0-100) from both inference and programmatic analysis"
    )
    
    # AEO/GEO Enhancement fields (new)
    answer_readiness_score: int = Field(
        ge=0,
        le=100,
        default=50,
        description="How well pages are optimized for featured snippets and direct answers (0-100)"
    )
    citation_trust_score: int = Field(
        ge=0,
        le=100,
        default=50,
        description="Likelihood of content being cited by AI systems (0-100)"
    )
    voice_search_readiness: VoiceSearchReadiness = Field(
        default=VoiceSearchReadiness.NEEDS_IMPROVEMENT,
        description="Voice search optimization level: excellent, good, needs_improvement, poor"
    )
    aeo_recommendations: List[str] = Field(
        default_factory=list,
        description="Specific recommendations for Answer Engine Optimization"
    )
    geo_recommendations: List[str] = Field(
        default_factory=list,
        description="Specific recommendations for Generative Engine Optimization"
    )
    schema_quality_for_ai: SchemaQualityForAI = Field(
        default=SchemaQualityForAI.BASIC,
        description="Schema markup quality for AI citation: none, basic, good, excellent"
    )


# Module exports
__all__ = [
    "InferenceIssue",
    "ProgrammaticSummary",
    "TechnicalAuditReportSchema",
    "VoiceSearchReadiness",
    "SchemaQualityForAI",
]
