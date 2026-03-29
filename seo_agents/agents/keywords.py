"""
KeywordResearchAgent (Agent 04) — performs keyword research with AEO/GEO enhancements.

IMPORTANT: In the new architecture, Agent 08 (Competitor) runs AFTER Agent 04.
So competitor_matrix is NOT available as input to this agent.

Input Requirements:
    - state.seo_project_context (from Agent 01) - industry, target_audience, key_products_services
    - state.site_inventory (from Agent 02) - existing page titles and content themes

Output:
    - KeywordUniverseSchema - comprehensive keyword universe with AEO/GEO fields

Dependencies:
    - Agent 01 must be complete (seo_project_context required)
    - Agent 02 must be complete (site_inventory required)
    - Gate 1 (gate1_technical) must be approved before running

Gate Logic:
    - This agent does NOT trigger an approval gate
    - Pipeline continues immediately to Agent 05

Usage:
    agent = KeywordResearchAgent(gemini_client, model, storage_dir)
    await agent.execute(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Dict, List

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState

if TYPE_CHECKING:
    from seo_agents.validators.schemas.keyword_universe import KeywordUniverseSchema


# Constants for defaults
DEFAULT_CITATION_SCORE = 5
MIN_CITATION_SCORE = 1
MAX_CITATION_SCORE = 10


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


class KeywordResearchAgent(SEOBaseAgent):
    """Agent 04: Keyword Research - generates comprehensive keyword universe with AEO/GEO."""

    agent_name: ClassVar[str] = "agent_04_keywords"
    triggers_approval_gate: ClassVar[bool] = False

    def _validate_inputs(self, state: SEOState) -> None:
        """Validate required input fields exist before running the agent.
        
        Args:
            state: SEOState with seo_project_context from Agent 01 and site_inventory from Agent 02
            
        Raises:
            ValueError: If seo_project_context or site_inventory is missing
        """
        if not state.seo_project_context:
            raise ValueError("seo_project_context required (run Agent 01 first)")
        
        if not state.site_inventory:
            raise ValueError("site_inventory required (run Agent 02 first)")

    def _validate_outputs(self, state: SEOState) -> None:
        """Validate output was properly set by the agent.
        
        Args:
            state: SEOState that should contain keyword_universe
            
        Raises:
            ValueError: If keyword_universe is not set or fails schema validation
        """
        from seo_agents.validators.schemas.keyword_universe import KeywordUniverseSchema
        
        if not state.keyword_universe:
            raise ValueError("keyword_universe was not set by KeywordResearchAgent")
        
        # Validate against schema (will raise if invalid)
        KeywordUniverseSchema(**state.keyword_universe)

    def _normalize_keyword_entry(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a keyword entry to match the schema.
        
        Args:
            entry: Raw keyword dictionary from LLM response
            
        Returns:
            Normalized keyword dictionary ready for Pydantic validation
        """
        from seo_agents.validators.schemas.keyword_universe import (
            KeywordEntry, KeywordIntent, VolumeTier, CompetitionTier, 
            KeywordSource, QueryFormat, AnswerSurface
        )
        
        normalized = entry.copy()
        
        # Normalize enum fields using helper function
        normalized["intent"] = _normalize_enum_value(
            normalized.get("intent"), KeywordIntent, KeywordIntent.INFORMATIONAL
        )
        normalized["volume_tier"] = _normalize_enum_value(
            normalized.get("volume_tier"), VolumeTier, VolumeTier.MEDIUM
        )
        normalized["competition_tier"] = _normalize_enum_value(
            normalized.get("competition_tier"), CompetitionTier, CompetitionTier.MEDIUM
        )
        normalized["source"] = _normalize_enum_value(
            normalized.get("source"), KeywordSource, KeywordSource.EXPANSION
        )
        normalized["query_format"] = _normalize_enum_value(
            normalized.get("query_format"), QueryFormat, QueryFormat.KEYWORD
        )
        
        # Normalize answer_surfaces to enum list
        surfaces = normalized.get("answer_surfaces", [])
        if isinstance(surfaces, str):
            surfaces = [surfaces]
        elif surfaces is None:
            surfaces = []
        
        normalized_surfaces = []
        for s in surfaces:
            normalized_surfaces.append(
                _normalize_enum_value(s, AnswerSurface, AnswerSurface.FEATURED_SNIPPET)
            )
        normalized["answer_surfaces"] = normalized_surfaces if normalized_surfaces else [AnswerSurface.FEATURED_SNIPPET]
        
        # citation_value_score with bounds using module constants
        score = normalized.get("citation_value_score", DEFAULT_CITATION_SCORE)
        try:
            normalized["citation_value_score"] = max(MIN_CITATION_SCORE, min(MAX_CITATION_SCORE, int(score)))
        except (ValueError, TypeError):
            normalized["citation_value_score"] = DEFAULT_CITATION_SCORE
        
        # Validate with Pydantic to ensure schema compliance
        return KeywordEntry(**normalized).model_dump()

    def _calculate_summary_fields(
        self, 
        keywords: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """Calculate summary fields from keyword list.
        
        Args:
            keywords: List of normalized keyword entries
            
        Returns:
            Dictionary with summary counts
        """
        featured_snippet_count = 0
        voice_search_count = 0
        ai_overview_count = 0
        high_citation_count = 0
        
        for kw in keywords:
            surfaces = kw.get("answer_surfaces", [])
            if "featured_snippet" in surfaces:
                featured_snippet_count += 1
            if "voice_assistant" in surfaces:
                voice_search_count += 1
            if "ai_overview" in surfaces:
                ai_overview_count += 1
            if kw.get("citation_value_score", 0) >= 8:
                high_citation_count += 1
        
        return {
            "featured_snippet_opportunities": featured_snippet_count,
            "voice_search_opportunities": voice_search_count,
            "ai_overview_opportunities": ai_overview_count,
            "high_citation_value_keywords": high_citation_count,
        }

    async def run(self, state: SEOState) -> None:
        """Execute the keyword research agent.
        
        Args:
            state: SEOState with seo_project_context from Agent 01 and site_inventory from Agent 02
            
        Returns:
            None - Results are stored in state.keyword_universe
        """
        from seo_agents.prompts.keywords import build_keyword_research_prompt
        from seo_agents.validators.schemas.keyword_universe import KeywordUniverseSchema

        self.log("Starting keyword research")

        # Extract required data
        seo_project_context = state.seo_project_context
        site_inventory = state.site_inventory

        # Build prompt (NOTE: No competitor_matrix - Agent 04 runs after Agent 05)
        prompt = build_keyword_research_prompt(
            seo_project_context=seo_project_context,
            site_inventory=site_inventory,
        )

        # Execute keyword research via LLM
        raw_universe = await self._call_gemini(prompt=prompt)

        # Normalize keyword entries
        normalized_keywords = []
        for entry in raw_universe.get("keywords", []):
            normalized_keywords.append(self._normalize_keyword_entry(entry))

        # Calculate summary fields
        summary_fields = self._calculate_summary_fields(normalized_keywords)

        # Ensure seed_terms_used exists
        seed_terms = raw_universe.get("seed_terms_used", [])
        if isinstance(seed_terms, str):
            seed_terms = [seed_terms]
        elif seed_terms is None:
            seed_terms = []

        # Build final normalized universe
        normalized_universe = {
            "total_keywords": raw_universe.get("total_keywords", len(normalized_keywords)),
            "keywords": normalized_keywords,
            "seed_terms_used": seed_terms,
            **summary_fields,
        }

        # Validate against schema
        validated_universe = KeywordUniverseSchema(**normalized_universe)

        # Store in state
        state.keyword_universe = validated_universe.model_dump()
        
        # Consolidated log statement with all summary fields
        self.log(
            f"Keyword research complete. "
            f"Total: {validated_universe.total_keywords} | "
            f"Featured: {validated_universe.featured_snippet_opportunities} | "
            f"Voice: {validated_universe.voice_search_opportunities} | "
            f"AI Overview: {validated_universe.ai_overview_opportunities} | "
            f"High Citation: {validated_universe.high_citation_value_keywords}"
        )

    def __all__(self) -> list[str]:
        return ["KeywordResearchAgent", self.agent_name]
