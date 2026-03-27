"""
MonitoringAgent (Agent 14) — monitors performance and generates re-optimization queue.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class MonitoringAgent(SEOBaseAgent):
    agent_name = "agent_14_monitoring"
    triggers_approval_gate = True

    async def run(self, state: SEOState) -> None:
        if not state.site_inventory or not state.page_keyword_map or not state.seo_priority_backlog:
            raise ValueError("site_inventory, page_keyword_map, and seo_priority_backlog required")

        from seo_agents.prompts.monitoring import build_monitoring_prompt

        prompt = build_monitoring_prompt(
            state.site_inventory,
            state.page_keyword_map,
            state.seo_priority_backlog,
            state.performance_dashboard,
        )

        result = await self._call_gemini(prompt)

        state.performance_dashboard = result.get("performance_dashboard")
        state.reoptimization_queue = result.get("reoptimization_queue")
        state.status = "monitoring"