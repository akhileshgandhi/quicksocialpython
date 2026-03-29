"""
PageMappingAgent (Agent 06) — maps keyword clusters to existing pages or identifies new pages needed.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class PageMappingAgent(SEOBaseAgent):
    agent_name = "agent_06_page_mapping"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.site_inventory or not state.keyword_clusters:
            raise ValueError("site_inventory and keyword_clusters required")

        from seo_agents.prompts.page_mapping import build_page_mapping_prompt

        prompt = build_page_mapping_prompt(
            state.site_inventory,
            state.keyword_clusters,
        )

        mapping = await self._call_gemini(prompt)

        state.page_keyword_map = mapping
        state.status = "intelligence"