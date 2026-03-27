"""Pydantic schema for technical audit report."""
from typing import List, Optional
from pydantic import BaseModel


class TechnicalIssue(BaseModel):
    issue_type: str
    severity: str  # "critical", "warning", "info"
    affected_urls: List[str]
    description: str
    recommendation: str


class TechnicalAuditReportSchema(BaseModel):
    total_issues: int
    critical_issues: List[TechnicalIssue]
    warnings: List[TechnicalIssue]
    info: List[TechnicalIssue]
    overall_health_score: int  # 0-100
