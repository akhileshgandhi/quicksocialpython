"""
ClusteringAgent (Agent 05) — clusters keywords into semantic groups.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class ClusteringAgent(SEOBaseAgent):
    agent_name = "agent_05_clustering"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.keyword_universe:
            raise ValueError("keyword_universe required (run Agent 04 first)")

        from seo_agents.prompts.clustering import build_clustering_prompt

        prompt = build_clustering_prompt(state.keyword_universe)

        clusters = await self._call_gemini(prompt)

        state.keyword_clusters = clusters
        state.status = "intelligence"