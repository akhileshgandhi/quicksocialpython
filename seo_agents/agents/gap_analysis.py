"""
GapAnalysisAgent (Agent 08) — analyzes content gaps vs competitors.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class GapAnalysisAgent(SEOBaseAgent):
    agent_name = "agent_08_gap_analysis"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.page_keyword_map or not state.competitor_matrix or not state.keyword_clusters:
            raise ValueError("page_keyword_map, competitor_matrix, and keyword_clusters required")

        from seo_agents.prompts.gap_analysis import build_gap_analysis_prompt

        prompt = build_gap_analysis_prompt(
            state.page_keyword_map,
            state.competitor_matrix,
            state.keyword_clusters,
        )

        report = await self._call_gemini(prompt)

        state.content_gap_report = report
        state.status = "strategy"