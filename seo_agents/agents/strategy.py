"""
StrategyAgent (Agent 09) — creates prioritized SEO backlog.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class StrategyAgent(SEOBaseAgent):
    agent_name = "agent_09_strategy"
    triggers_approval_gate = True

    async def run(self, state: SEOState) -> None:
        if not state.technical_audit_report or not state.content_gap_report or not state.page_keyword_map or not state.seo_project_context:
            raise ValueError("technical_audit_report, content_gap_report, page_keyword_map, and seo_project_context required")

        from seo_agents.prompts.strategy import build_strategy_prompt

        prompt = build_strategy_prompt(
            state.technical_audit_report,
            state.content_gap_report,
            state.page_keyword_map,
            state.seo_project_context,
        )

        backlog = await self._call_gemini(prompt)

        state.seo_priority_backlog = backlog
        state.status = "strategy"