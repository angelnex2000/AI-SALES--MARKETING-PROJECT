from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    """Shared interface for all AI agents. Each agent must implement run()."""

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent and return structured output."""
        ...
