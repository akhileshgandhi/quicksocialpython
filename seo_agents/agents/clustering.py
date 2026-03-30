"""
ClusteringAgent (Agent 05) — groups keywords into semantic clusters.

Groups semantically related keywords into intent-aligned clusters. Each cluster
maps to exactly one target URL and one dominant answer intent. This prevents
content cannibalization and splits ranking authority.

Input Requirements:
    - state.keyword_universe (from Agent 04) - comprehensive keyword list with intent and volume tiers
    - state.seo_project_context (from Agent 01) - for cluster naming context

Output:
    - KeywordClustersSchema - keyword clusters with AEO/GEO optimizations

Dependencies:
    - Agent 04 must be complete (keyword_universe required)

Gate Logic:
    - This agent does NOT trigger an approval gate
    - Pipeline continues immediately to Agent 06 (Page Mapping)

Usage:
    agent = ClusteringAgent(gemini_client, model, storage_dir)
    await agent.execute(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState

if TYPE_CHECKING:
    from seo_agents.validators.schemas.keyword_clusters import KeywordClustersSchema


def _normalize_enum_value(
    raw_value: Any,
    enum_class: Any,
    default: Any,
) -> Any:
    """Helper to normalize enum values with fallback to default.
    
    Args:
        raw_value: Raw value from LLM response
        enum_class: Pydantic Enum class to validate against
        default: Default value if validation fails
        
    Returns:
        Normalized enum value
    """
    if raw_value is None:
        return default
    
    try:
        # Handle string input by normalizing
        if isinstance(raw_value, str):
            return enum_class(raw_value.lower())
        return enum_class(raw_value)
    except (ValueError, AttributeError):
        return default


def _normalize_list_field(
    raw_list: Any,
    item_type: str = "str",
    default: List = None,
) -> List:
    """Normalize a list field, handling various input formats.
    
    Args:
        raw_list: Raw list from LLM (can be string, list, or None)
        item_type: Type hint for items (not enforced strictly)
        default: Default value if normalization fails
        
    Returns:
        Normalized list
    """
    if default is None:
        default = []
    
    if raw_list is None:
        return default
    
    if isinstance(raw_list, str):
        # Handle comma-separated string
        return [s.strip() for s in raw_list.split(",") if s.strip()]
    
    if isinstance(raw_list, list):
        return [str(item) for item in raw_list if item]
    
    return default


class ClusteringAgent(SEOBaseAgent):
    """Agent 05: Keyword Clustering - groups keywords into semantic clusters with AEO/GEO."""

    agent_name: ClassVar[str] = "agent_05_clustering"
    triggers_approval_gate: ClassVar[bool] = False

    def _validate_inputs(self, state: SEOState) -> None:
        """Validate required input fields exist before running the agent.
        
        Args:
            state: SEOState with keyword_universe from Agent 04
            
        Raises:
            ValueError: If keyword_universe is missing
        """
        if not state.keyword_universe:
            raise ValueError("keyword_universe required (run Agent 04 first)")

    def _validate_outputs(self, state: SEOState) -> None:
        """Validate output was properly set by the agent.
        
        Args:
            state: SEOState that should contain keyword_clusters
            
        Raises:
            ValueError: If keyword_clusters is not set or fails schema validation
        """
        from seo_agents.validators.schemas.keyword_clusters import KeywordClustersSchema
        
        if not state.keyword_clusters:
            raise ValueError("keyword_clusters was not set by ClusteringAgent")
        
        # Validate against schema (will raise if invalid)
        KeywordClustersSchema(**state.keyword_clusters)

    def _normalize_cluster_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a cluster entry to match the schema.
        
        Args:
            entry: Raw cluster dictionary from LLM response
            
        Returns:
            Normalized cluster dictionary ready for Pydantic validation
        """
        from seo_agents.validators.schemas.keyword_clusters import (
            KeywordCluster, ClusterIntent, PageType, AnswerFormat, AnswerSurface
        )
        
        normalized = entry.copy()
        
        # Normalize enum fields using helper function
        normalized["intent"] = _normalize_enum_value(
            normalized.get("intent"), ClusterIntent, ClusterIntent.INFORMATIONAL
        )
        normalized["recommended_page_type"] = _normalize_enum_value(
            normalized.get("recommended_page_type"), PageType, PageType.BLOG_POST
        )
        normalized["answer_format"] = _normalize_enum_value(
            normalized.get("answer_format"), AnswerFormat, AnswerFormat.SHORT_PARAGRAPH
        )
        
        # Normalize supporting_keywords to list
        normalized["supporting_keywords"] = _normalize_list_field(
            normalized.get("supporting_keywords"),
            default=[]
        )
        
        # Normalize answer_surface_targets to enum list
        surfaces = normalized.get("answer_surface_targets", [])
        normalized_surfaces = []
        for s in _normalize_list_field(surfaces):
            normalized_surfaces.append(
                _normalize_enum_value(s, AnswerSurface, AnswerSurface.FEATURED_SNIPPET)
            )
        normalized["answer_surface_targets"] = normalized_surfaces if normalized_surfaces else []
        
        # Priority score with bounds
        score = normalized.get("priority_score", 50)
        try:
            normalized["priority_score"] = max(0, min(100, int(score)))
        except (ValueError, TypeError):
            normalized["priority_score"] = 50
        
        # Cannibalization risk with bounds
        risk = normalized.get("cannibalization_risk")
        if risk is not None:
            try:
                normalized["cannibalization_risk"] = max(0.0, min(1.0, float(risk)))
            except (ValueError, TypeError):
                normalized["cannibalization_risk"] = None
        
        # Validate with Pydantic to ensure schema compliance
        return KeywordCluster(**normalized).model_dump()

    def _calculate_summary_fields(
        self, 
        clusters: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate summary fields from cluster list.
        
        Args:
            clusters: List of normalized cluster dictionaries
            
        Returns:
            Dictionary with summary counts
        """
        featured_snippet_count = 0
        voice_search_count = 0
        ai_overview_count = 0
        high_priority_count = 0
        new_pages_count = 0
        hub_count = 0
        spoke_count = 0
        hub_ids = []
        spoke_ids = []
        
        clusters_by_intent = {}
        clusters_by_page_type = {}
        
        for cluster in clusters:
            # Count AEO/GEO opportunities
            surfaces = cluster.get("answer_surface_targets", [])
            if "featured_snippet" in surfaces:
                featured_snippet_count += 1
            if "voice_search" in surfaces:
                voice_search_count += 1
            if "ai_overview" in surfaces:
                ai_overview_count += 1
            
            # Count priority and page types
            if cluster.get("priority_score", 0) >= 80:
                high_priority_count += 1
            if cluster.get("is_new_page_required", False):
                new_pages_count += 1
            
            # Count internal linking roles
            link_priority = cluster.get("internal_link_priority")
            if link_priority == "hub":
                hub_count += 1
                hub_ids.append(cluster.get("cluster_id"))
            elif link_priority == "spoke":
                spoke_count += 1
                spoke_ids.append(cluster.get("cluster_id"))
            
            # Count by intent
            intent = cluster.get("intent", "informational")
            clusters_by_intent[intent] = clusters_by_intent.get(intent, 0) + 1
            
            # Count by page type
            page_type = cluster.get("recommended_page_type", "blog_post")
            clusters_by_page_type[page_type] = clusters_by_page_type.get(page_type, 0) + 1
        
        return {
            "clusters_by_intent": clusters_by_intent,
            "clusters_by_page_type": clusters_by_page_type,
            "new_pages_needed": new_pages_count,
            "high_priority_clusters": high_priority_count,
            "featured_snippet_candidates": featured_snippet_count,
            "voice_search_candidates": voice_search_count,
            "ai_overview_candidates": ai_overview_count,
            "hub_clusters": hub_ids,
            "spoke_clusters": spoke_ids,
        }

    async def run(self, state: SEOState) -> None:
        """Execute the keyword clustering agent.
        
        Args:
            state: SEOState with keyword_universe from Agent 04
            
        Returns:
            None - Results are stored in state.keyword_clusters
        """
        from seo_agents.prompts.clustering import build_clustering_prompt
        from seo_agents.validators.schemas.keyword_clusters import KeywordClustersSchema

        self.log("Starting keyword clustering")

        # Extract required data
        keyword_universe = state.keyword_universe
        seo_project_context = state.seo_project_context

        # Build prompt with keyword universe and context
        prompt = build_clustering_prompt(
            keyword_universe=keyword_universe,
            project_context=seo_project_context,
        )

        # Execute clustering via LLM
        raw_clusters = await self._call_gemini(prompt=prompt)

        # Normalize cluster entries
        normalized_clusters = []
        for entry in raw_clusters.get("clusters", []):
            normalized_clusters.append(self._normalize_cluster_entry(entry))

        # Calculate summary fields
        summary_fields = self._calculate_summary_fields(normalized_clusters)

        # Count total keywords clustered
        total_keywords_clustered = sum(
            len(c.get("supporting_keywords", [])) + 1 
            for c in normalized_clusters
        )

        # Build final normalized schema
        normalized_schema = {
            "total_clusters": raw_clusters.get("total_clusters", len(normalized_clusters)),
            "total_keywords_clustered": total_keywords_clustered,
            "clusters": normalized_clusters,
            **summary_fields,
        }

        # Validate against schema
        validated_clusters = KeywordClustersSchema(**normalized_schema)

        # Store in state
        state.keyword_clusters = validated_clusters.model_dump()
        state.status = "intelligence"
        
        # Consolidated log statement with all summary fields
        self.log(
            f"Keyword clustering complete. "
            f"Total: {validated_clusters.total_clusters} clusters | "
            f"Keywords: {validated_clusters.total_keywords_clustered} | "
            f"New Pages: {validated_clusters.new_pages_needed} | "
            f"Featured Snippet: {validated_clusters.featured_snippet_candidates} | "
            f"Voice: {validated_clusters.voice_search_candidates} | "
            f"AI Overview: {validated_clusters.ai_overview_candidates}"
        )

    def __all__(self) -> list[str]:
        return ["ClusteringAgent", self.agent_name]