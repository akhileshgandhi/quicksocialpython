"""
LinkingSchemaAgent (Agent 13) — generates internal linking structure and schema markup.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class LinkingSchemaAgent(SEOBaseAgent):
    agent_name = "agent_13_linking_schema"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.site_inventory or not state.page_keyword_map or not state.content_drafts or not state.seo_project_context:
            raise ValueError("site_inventory, page_keyword_map, content_drafts, and seo_project_context required")

        from seo_agents.prompts.linking_schema import build_linking_schema_prompt

        prompt = build_linking_schema_prompt(
            state.site_inventory,
            state.page_keyword_map,
            state.content_drafts,
            state.seo_project_context,
        )

        result = await self._call_gemini(prompt)

        state.internal_link_graph = result.get("internal_link_graph")
        state.schema_map = result.get("schema_map")
        state.status = "execution"