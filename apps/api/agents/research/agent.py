from typing import Any

from agents.base import BaseAgent


class ResearchAgent(BaseAgent):
    """Placeholder implementation. The real version calls an LLM (see
    prompts.py) to produce a company profile with source citations from
    public/CRM data. Returns a fixed shape now so the AI Orchestrator and
    downstream agents can be wired and tested before the real model lands.
    Output maps onto the ResearchReport table (AIOutputMixin + profile
    fields).
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_name": "research",
            "model_version": "research-stub-v0",
            "confidence": 0.0,
            "summary": "",
            "industry_insights": None,
            "company_size_estimate": None,
            "recent_news": None,
            "pain_points": None,
            "sources": None,
        }