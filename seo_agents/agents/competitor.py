"""
CompetitorAgent (Agent 04) — performs competitor analysis.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class CompetitorAgent(SEOBaseAgent):
    agent_name = "agent_04_competitor"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.seo_project_context or not state.site_inventory:
            raise ValueError("seo_project_context and site_inventory required")

        from seo_agents.prompts.competitor import build_competitor_prompt

        prompt = build_competitor_prompt(
            state.seo_project_context,
            state.site_inventory,
        )

        matrix = await self._call_gemini(prompt)

        state.competitor_matrix = matrix
        state.status = "intelligence"