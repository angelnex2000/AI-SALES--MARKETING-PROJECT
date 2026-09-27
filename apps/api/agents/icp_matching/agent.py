"""ICP Matching Agent.

Answers "should we sell to this company at all?" — a different question from
Buying Signals' "is now a good time?". A lead can score high here with no
signals (right company, wrong moment), or the reverse (something is happening,
but not at a company worth selling to).

Two rules shape the implementation:

* **The ICP belongs to the tenant, not to us.** The profile comes from
  `Company.icp_config` via `rules.resolve_profile()`; nothing about the target
  market is hardcoded here.
* **Unknown is not the same as bad.** Missing attributes score neutral and
  reduce `confidence` instead of scoring like a known mismatch — a lead nobody
  has researched must not rank below one we know is wrong.
"""

from typing import Any

from agents.base import BaseAgent
from agents.icp_matching import rules

MODEL_NAME = "icp_matching"
MODEL_VERSION = "icp-rules-v1"


class ICPMatchingAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        lead = input_data.get("lead") or {}
        signals = input_data.get("signals") or []
        profile = rules.resolve_profile(input_data.get("icp_profile"))

        industry_score, industry_known = rules.score_industry(lead.get("industry"), profile)
        size_score, size_known = rules.score_company_size(lead.get("employees"), profile)
        region_score, region_known = rules.score_region(lead.get("country"), profile)
        need_score, need_known = rules.score_need(signals)

        weights = profile["weights"]
        overall = (
            industry_score * weights["industry"]
            + size_score * weights["company_size"]
            + region_score * weights["region"]
            + need_score * weights["need"]
        )

        known = [industry_known, size_known, region_known, need_known]
        # Confidence is how much of the profile we could actually evaluate —
        # the same "coverage, not truth" meaning the Research Agent uses.
        confidence = round(sum(known) / len(known), 2)

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "industry_score": round(industry_score, 1),
            "company_size_score": round(size_score, 1),
            "region_score": round(region_score, 1),
            # The column is named pain_point_score for historical reasons; it
            # is the *need* dimension, scored from evidence-backed signals.
            "pain_point_score": round(need_score, 1),
            "overall_score": round(overall, 1),
            "confidence": confidence,
            "explanation": self._explanation(
                industry=(industry_score, industry_known, lead.get("industry")),
                size=(size_score, size_known, lead.get("employees")),
                region=(region_score, region_known, lead.get("country")),
                need=(need_score, need_known, f"{len(signals)} signal(s)"),
                overall=overall,
                confidence=confidence,
            ),
        }

    def _explanation(self, *, industry, size, region, need, overall, confidence) -> str:
        parts = [
            self._dimension("Industry", *industry),
            self._dimension("Size", *size),
            self._dimension("Region", *region),
            self._dimension("Need", *need),
        ]
        headline = f"Overall fit {overall:.0f}/100"
        if confidence < 1.0:
            headline += f" (evaluated on {confidence:.0%} of the profile)"
        return f"{headline}. " + "; ".join(parts) + "."

    def _dimension(self, label: str, score: float, known: bool, value: Any) -> str:
        if not known:
            return f"{label} {score:.0f} (no data — scored neutral, not penalised)"
        return f"{label} {score:.0f} ({value})"
