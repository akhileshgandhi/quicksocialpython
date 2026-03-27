"""
KeywordResearchAgent (Agent 05) — performs keyword research.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class KeywordResearchAgent(SEOBaseAgent):
    agent_name = "agent_05_keywords"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.seo_project_context or not state.site_inventory or not state.competitor_matrix:
            raise ValueError("seo_project_context, site_inventory, and competitor_matrix required")

        from seo_agents.prompts.keywords import build_keyword_research_prompt

        prompt = build_keyword_research_prompt(
            state.seo_project_context,
            state.site_inventory,
            state.competitor_matrix,
        )

        universe = await self._call_gemini(prompt)

        state.keyword_universe = universe
        state.status = "intelligence"