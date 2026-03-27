"""
OnPageAgent (Agent 10) — generates on-page optimization briefs.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class OnPageAgent(SEOBaseAgent):
    agent_name = "agent_10_on_page"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.seo_priority_backlog or not state.site_inventory or not state.page_keyword_map:
            raise ValueError("seo_priority_backlog, site_inventory, and page_keyword_map required")

        from seo_agents.prompts.on_page import build_on_page_prompt

        prompt = build_on_page_prompt(
            state.seo_priority_backlog,
            state.site_inventory,
            state.page_keyword_map,
        )

        briefs = await self._call_gemini(prompt)

        state.page_optimization_briefs = briefs
        state.status = "execution"