from typing import Any

from agents.base import BaseAgent


class ICPMatchingAgent(BaseAgent):
    """Placeholder implementation. The real version scores per-attribute fit
    against ICP rules (see rules.py) and returns each attribute score
    explicitly (never just a single overall number), matching the ICPScore
    table's fixed columns.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_name": "icp_matching",
            "model_version": "icp-stub-v0",
            "confidence": 0.0,
            "industry_score": 0.0,
            "company_size_score": 0.0,
            "region_score": 0.0,
            "pain_point_score": 0.0,
            "overall_score": 0.0,
        }