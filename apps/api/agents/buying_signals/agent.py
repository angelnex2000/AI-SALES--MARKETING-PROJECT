from typing import Any

from agents.base import BaseAgent


class BuyingSignalAgent(BaseAgent):
    """Placeholder implementation. The real version scans research + news
    for signals like hiring, expansion, and funding (see signals.py for the
    rule definitions). Each returned signal carries its own type,
    description, source_url, and confidence — matching the BuyingSignal
    table.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return {"model_name": "buying_signals", "model_version": "buying-signal-stub-v0", "signals": []}