"""
ContentBriefAgent (Agent 11) — generates content briefs for new content items.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class ContentBriefAgent(SEOBaseAgent):
    agent_name = "agent_11_content_brief"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.seo_priority_backlog or not state.content_gap_report or not state.keyword_clusters or not state.seo_project_context:
            raise ValueError("seo_priority_backlog, content_gap_report, keyword_clusters, and seo_project_context required")

        from seo_agents.prompts.content_brief import build_content_brief_prompt

        prompt = build_content_brief_prompt(
            state.seo_priority_backlog,
            state.content_gap_report,
            state.keyword_clusters,
            state.seo_project_context,
        )

        briefs = await self._call_gemini(prompt)

        state.content_briefs = briefs
        state.status = "execution"