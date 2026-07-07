from typing import Any

from agents.base import BaseAgent


class LeadScoringAgent(BaseAgent):
    """Placeholder implementation. The real version is the ML/DL model
    trained in train.py (see features.py) and loaded from artifacts/;
    model_name/model_version resolve against ModelRegistryEntry. Returns a
    fixed shape so callers don't need to change once the real model is
    trained.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "model_name": "lead_scoring",
            "model_version": "lead-scoring-stub-v0",
            "score": 0,
            "confidence": 0.0,
        }