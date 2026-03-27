"""
IntakeAgent (Agent 01) — processes user form data into structured business context.

Input: User-submitted form data (business name, website URL, industry, etc.)
Output: seo_project_context dict
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class IntakeAgent(SEOBaseAgent):
    agent_name = "agent_01_intake"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        from seo_agents.prompts.intake import build_intake_prompt

        if not state.website_url:
            raise ValueError("website_url is required")

        prompt = build_intake_prompt(
            website_url=state.website_url,
            brand_id=state.brand_id,
            config=state.config,
        )

        context = await self._call_gemini(prompt)

        state.seo_project_context = context
        state.status = "intelligence"