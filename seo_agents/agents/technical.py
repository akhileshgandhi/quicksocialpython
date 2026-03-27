"""
TechnicalAuditAgent (Agent 03) — performs technical SEO audit of all crawled pages.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class TechnicalAuditAgent(SEOBaseAgent):
    agent_name = "agent_03_technical"
    triggers_approval_gate = True

    async def run(self, state: SEOState) -> None:
        if not state.site_inventory:
            raise ValueError("site_inventory required (run Agent 02 first)")

        from seo_agents.prompts.technical import build_technical_audit_prompt

        prompt = build_technical_audit_prompt(state.site_inventory)

        report = await self._call_gemini(prompt)

        state.technical_audit_report = report
        state.status = "intelligence"