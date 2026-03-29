"""
SEO Constants — time budgets, gate mappings, layer definitions.
"""

SEO_TIME_BUDGETS = {
    "agent_01_intake": 30,
    "agent_02_crawl": 300,
    "agent_03_technical": 300,
    "agent_04_keywords": 300,
    "agent_05_clustering": 180,
    "agent_06_page_mapping": 60,
    "agent_08_competitor": 180,
    "agent_07_gap_analysis": 60,
    "agent_09_strategy": 60,
    "agent_10_on_page": 120,
    "agent_11_content_brief": 120,
    "agent_12_content_writer": 300,
    "agent_13_linking_schema": 120,
    "agent_14_monitoring": 180,
}

GATE_TRIGGER_MAP = {
    "agent_03_technical": "gate1_technical",
    "agent_09_strategy": "gate2_strategy",
    "agent_12_content_writer": "gate3_content",
    "agent_14_monitoring": "gate4_reoptimization",
}

GATE_BLOCK_MAP = {
    # In the new architecture, Agent 04 (keywords) runs AFTER Gate 1 approval
    # Agent 08 (competitor) runs AFTER Agent 04-06, so it's not blocked by Gate 1
    "agent_04_keywords": "gate1_technical",
    "agent_10_on_page": "gate2_strategy",
    "agent_13_linking_schema": "gate3_content",
}

LAYER_AGENTS = {
    # Layer 1: Discovery - intake, crawl, technical audit
    1: [
        "agent_01_intake",
        "agent_02_crawl",
        "agent_03_technical",
    ],
    # Layer 2: Intelligence - keywords first, THEN competitor analysis
    # NEW ORDER: Agent 04-06 run BEFORE Agent 08 for meaningful competitor comparison
    2: [
        "agent_04_keywords",
        "agent_05_clustering",
        "agent_06_page_mapping",
        "agent_08_competitor",
        "agent_07_gap_analysis",
    ],
    # Layer 3: Strategy
    3: ["agent_09_strategy"],
    # Layer 4: Execution
    4: [
        "agent_10_on_page",
        "agent_11_content_brief",
        "agent_12_content_writer",
        "agent_13_linking_schema",
    ],
    # Layer 5: Growth Loop
    5: ["agent_14_monitoring"],
}

SEO_DATA_TYPES = [
    "seo_project_context",
    "site_inventory",
    "technical_audit_report",
    "competitor_matrix",
    "keyword_universe",
    "keyword_clusters",
    "page_keyword_map",
    "content_gap_report",
    "seo_priority_backlog",
    "page_optimization_briefs",
    "content_briefs",
    "content_drafts",
    "internal_link_graph",
    "schema_map",
    "performance_dashboard",
    "reoptimization_queue",
]

ALL_AGENTS = [
    "agent_01_intake",
    "agent_02_crawl",
    "agent_03_technical",
    "agent_04_keywords",
    "agent_05_clustering",
    "agent_06_page_mapping",
    "agent_08_competitor",
    "agent_07_gap_analysis",
    "agent_09_strategy",
    "agent_10_on_page",
    "agent_11_content_brief",
    "agent_12_content_writer",
    "agent_13_linking_schema",
    "agent_14_monitoring",
]

GATE_NAMES = [
    "gate1_technical",
    "gate2_strategy",
    "gate3_content",
    "gate4_reoptimization",
]

# Health score weights for Agent 03 (TechnicalAuditAgent)
HEALTH_SCORE_WEIGHTS = {
    # Inference issues (per issue)
    "critical_inference": 15,
    "warning_inference": 5,
    "info_inference": 0,  # Info doesn't affect score
    # Programmatic issues (per issue, with caps)
    "duplicate_title": 3,
    "duplicate_title_max": 20,
    "duplicate_meta": 3,
    "duplicate_meta_max": 20,
    "thin_content": 2,
    "thin_content_max": 15,
    # Broken links impact
    "broken_link": 2,
    "broken_link_max": 10,
}

# Maximum deductions per category (to prevent negative scores)
HEALTH_SCORE_MAX_DEDUCTIONS = {
    "inference_critical": 30,  # Max 2 critical issues
    "inference_warnings": 20,  # Max 4 warning issues
    "programmatic": 55,  # Combined max
}