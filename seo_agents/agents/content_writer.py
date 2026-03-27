"""
ContentWriterAgent (Agent 12) — generates full content drafts.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class ContentWriterAgent(SEOBaseAgent):
    agent_name = "agent_12_content_writer"
    triggers_approval_gate = True

    async def run(self, state: SEOState) -> None:
        if not state.content_briefs or not state.seo_project_context:
            raise ValueError("content_briefs and seo_project_context required")

        from seo_agents.prompts.content_writer import build_content_writer_prompt

        prompt = build_content_writer_prompt(
            state.content_briefs,
            state.seo_project_context,
        )

        drafts = await self._call_gemini(prompt)

        state.content_drafts = drafts
        state.status = "execution"