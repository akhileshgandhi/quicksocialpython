"""
IntakeAgent (Agent 01) — processes user form data into structured business context.

Input: User-submitted form data (business name, website URL, industry, etc.)
Output: seo_project_context dict

Functional Logic:
1. Accept user-provided form data from state.config["intake_form_data"]
2. Build a prompt using build_intake_prompt_with_form_data for richer context
3. Call _call_gemini() with the prompt and response schema validation
4. Store validated response in state.seo_project_context
5. Update status to "intelligence"

Gate Logic: None — pipeline continues immediately
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Type

from seo_agents.base_agent import SEOBaseAgent
from seo_agents.state import SEOState

if TYPE_CHECKING:
    from seo_agents.validators.schemas.seo_project_context import SEOProjectContextSchema


class IntakeAgent(SEOBaseAgent):
    """Agent 01: Intake - Process user form data into structured business context."""
    
    agent_name: ClassVar[str] = "agent_01_intake"
    triggers_approval_gate: ClassVar[bool] = False

    def __all__(self) -> list[str]:
        return ["IntakeAgent", self.agent_name]
    
    def _validate_inputs(self, state: SEOState) -> None:
        """Validate required input fields exist before running the agent."""
        if not state.website_url:
            raise ValueError("website_url is required for IntakeAgent")
        
        # Basic URL validation
        if not (
            state.website_url.startswith("http://") or 
            state.website_url.startswith("https://")
        ):
            raise ValueError(f"Invalid website_url format: {state.website_url}")

    def _validate_outputs(self, state: SEOState) -> None:
        """Validate output was properly set."""
        from seo_agents.validators.schemas.seo_project_context import SEOProjectContextSchema
        
        if not state.seo_project_context:
            raise ValueError("seo_project_context was not set by IntakeAgent")
        
        # Validate against schema (will raise if invalid)
        SEOProjectContextSchema(**state.seo_project_context)

    async def run(self, state: SEOState) -> None:
        """Run the intake agent to synthesize business context."""
        from seo_agents.prompts.intake import build_intake_prompt_with_form_data
        from seo_agents.validators.schemas.seo_project_context import SEOProjectContextSchema

        self.log(f"Processing intake for website: {state.website_url}")

        # Get form data from config (stored during project creation)
        form_data = state.config.get("intake_form_data", {})
        
        # Build prompt using the enhanced function that accepts form data
        prompt = build_intake_prompt_with_form_data(
            website_url=state.website_url,
            business_name=form_data.get("business_name"),
            industry=form_data.get("industry"),
            target_audience=form_data.get("target_audience"),
            primary_goals=form_data.get("primary_goals"),
            competitors=form_data.get("competitors"),
            brand_voice=form_data.get("brand_voice"),
            key_products_services=form_data.get("key_products_services"),
            brand_id=state.brand_id,
            config=state.config,
        )

        context = await self._call_gemini(
            prompt=prompt,
            response_schema=SEOProjectContextSchema
        )

        state.seo_project_context = context
        state.status = "intelligence"
        
        self.log(f"Intake complete. Business: {context.get('business_name', 'Unknown')}")