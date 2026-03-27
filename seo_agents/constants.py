"""
SEO Constants — time budgets, gate mappings, layer definitions.
"""

SEO_TIME_BUDGETS = {
    "agent_01_intake": 30,
    "agent_02_crawl": 300,
    "agent_03_technical": 300,
    "agent_04_competitor": 180,
    "agent_05_keywords": 300,
    "agent_06_clustering": 180,
    "agent_07_page_mapping": 60,
    "agent_08_gap_analysis": 60,
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
    "agent_04_competitor": "gate1_technical",
    "agent_10_on_page": "gate2_strategy",
    "agent_13_linking_schema": "gate3_content",
}

LAYER_AGENTS = {
    1: [
        "agent_01_intake",
        "agent_02_crawl",
        "agent_03_technical",
        "agent_04_competitor",
        "agent_05_keywords",
    ],
    2: [
        "agent_06_clustering",
        "agent_07_page_mapping",
        "agent_08_gap_analysis",
    ],
    3: ["agent_09_strategy"],
    4: [
        "agent_10_on_page",
        "agent_11_content_brief",
        "agent_12_content_writer",
        "agent_13_linking_schema",
    ],
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
    "agent_04_competitor",
    "agent_05_keywords",
    "agent_06_clustering",
    "agent_07_page_mapping",
    "agent_08_gap_analysis",
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