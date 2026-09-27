"""Buying Signal Agent.

Scans a research report for evidence that something is happening at the
company right now — funding, hiring, expansion, a new decision-maker.

**Signals are read from EVIDENCE ONLY, never from inference.** This is the
whole design, and skipping it produces a system that launders assumptions
into numbers:

    industry = "Healthcare"
      -> Research infers pain point "High patient inquiry volume"
      -> Buying Signals matches "inquiry volume"
      -> emits a support_load signal at 0.75
      -> Lead Scoring reads that signal and raises the lead's score

Nothing happened at that company. One industry field became a confident claim
that they are ready to buy, and a rep calls them because of it. So
`pain_points` and `sales_opportunities` (typed `Hypothesis` in
`agents/research/schemas.py`) are deliberately **not** scanned — only
`recent_news`, which carries `Evidence{claim, source}`.

The consequence is that a lead with no news and no CRM notes yields zero
signals. That is the correct answer, not a gap to paper over: we genuinely
have no evidence about timing.
"""

from typing import Any

from agents.base import BaseAgent
from agents.buying_signals.signals import RULES, is_negated, matches

MODEL_NAME = "buying_signals"
MODEL_VERSION = "buying-signals-rules-v1"

# A signal cannot be more certain than the report it was read from: a thin
# report (coverage 0.2) that happens to contain "expansion" should not yield
# an 0.85 signal. The floor is generous — even a thin report containing a
# real, sourced news item is worth something.
MIN_COVERAGE_FACTOR = 0.5


class BuyingSignalAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        research = input_data.get("research") or {}
        evidence = research.get("recent_news") or []
        coverage = float(research.get("confidence") or 0.0)

        signals: list[dict[str, Any]] = []
        seen: set[str] = set()

        for item in evidence:
            # Defensive: Evidence is {claim, source}, but a future LLM path
            # could hand back a bare string. Don't crash the pipeline over it.
            claim = item.get("claim", "") if isinstance(item, dict) else str(item)
            source = item.get("source", "unknown") if isinstance(item, dict) else "unknown"
            if not claim:
                continue

            if is_negated(claim):
                # "Announced a hiring freeze" must not read as growth.
                continue

            for rule in RULES:
                phrase = matches(rule, claim)
                # One signal per type per run: three news items mentioning
                # expansion is one expansion signal, not three.
                if not phrase or rule.signal_type.value in seen:
                    continue
                seen.add(rule.signal_type.value)
                signals.append(
                    {
                        "signal_type": rule.signal_type.value,
                        "description": rule.description,
                        "confidence": self._scaled_confidence(rule.base_confidence, coverage),
                        "explanation": f'Matched "{phrase}" in evidence from {source}: "{claim}"',
                        "source_url": source if source.startswith("http") else None,
                        "matched_phrase": phrase,
                        "evidence_source": source,
                    }
                )

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "signals": signals,
            "confidence": max((s["confidence"] for s in signals), default=0.0),
            "explanation": self._explanation(signals, evidence),
        }

    def _scaled_confidence(self, base: float, coverage: float) -> float:
        factor = MIN_COVERAGE_FACTOR + (1.0 - MIN_COVERAGE_FACTOR) * coverage
        return round(base * factor, 2)

    def _explanation(self, signals: list[dict[str, Any]], evidence: list) -> str:
        if not evidence:
            return (
                "No signals: the research report contains no evidenced claims. "
                "Inferred pain points are deliberately not scanned — a signal "
                "derived from an assumption is not evidence of timing."
            )
        if not signals:
            return f"No signals matched across {len(evidence)} evidenced claim(s)."
        kinds = ", ".join(s["signal_type"] for s in signals)
        return f"Detected {len(signals)} signal(s) from {len(evidence)} evidenced claim(s): {kinds}."
