"""
CrawlAgent (Agent 02) — performs async breadth-first crawl of the website.
"""

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState


class CrawlAgent(SEOBaseAgent):
    agent_name = "agent_02_crawl"
    triggers_approval_gate = False

    async def run(self, state: SEOState) -> None:
        if not state.seo_project_context:
            raise ValueError("seo_project_context required (run Agent 01 first)")

        website_url = state.seo_project_context.get("website_url", state.website_url)
        if not website_url:
            raise ValueError("website_url is required")

        from seo_agents.prompts.crawl import build_crawl_prompt

        crawl_depth = state.config.get("crawl_depth", 3)
        max_pages = state.config.get("max_pages", 500)

        prompt = build_crawl_prompt(website_url, crawl_depth, max_pages)

        inventory = await self._call_gemini(prompt)

        state.site_inventory = inventory
        state.status = "intelligence"