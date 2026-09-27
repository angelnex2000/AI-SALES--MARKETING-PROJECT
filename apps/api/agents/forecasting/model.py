"""Revenue Forecasting Agent — inference.

Answers the question leadership asks: *how much will we close this period?*

    committed   (deals already won in the period)      -> banked, certainty 1
    weighted    (sum of open amount x P(win | stage))  -> expected value
                                                       = predicted revenue

Read `features.py` first for why this is weighted pipeline rather than the
brief's XGBoost regression: 43 monthly rows, and tree models cannot
extrapolate a growing pipeline.

## Honest reporting

`confidence` is **measured, never chosen**. It is derived from the backtested
accuracy of this exact method on historical months (`artifacts/metrics.json`),
then reduced by things that are wrong with *this* pipeline right now — deals
with no amount, stage rates with thin support, and how far ahead the period is.
The brief's worked example reports 0.87 next to a number nobody validated;
here, an uncalibrated workspace reports `UNCALIBRATED_CONFIDENCE` and says so
in `explanation`.

## Currency

One forecast per currency, never a summed total. Adding a USD deal to an INR
deal produces a figure that is not money, and there is no FX source in this
service — the same rule `deal_service.pipeline_board` follows with
`totals_by_currency`.
"""

import json
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from agents.forecasting import features

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
CALIBRATION_PATH = ARTIFACT_DIR / "stage_win_rates.json"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

MODEL_NAME = "revenue_forecasting"
MODEL_VERSION = "revenue-weighted-pipeline-v1"

# No pipeline arithmetic justifies more than this. A forecast is a statement
# about deals that have not happened yet.
MAX_CONFIDENCE = 0.85

# Used when no backtest artifact exists — a fresh checkout has none, because
# artifacts are gitignored. Low on purpose: the method is unvalidated *here*,
# whatever it scored on our development data.
UNCALIBRATED_CONFIDENCE = 0.25

# Confidence decay per period beyond the current one, floored. Forecasting
# next quarter from today's pipeline is a weaker claim than forecasting the
# month we are already inside.
HORIZON_DECAY = 0.85
MIN_HORIZON_FACTOR = 0.40

# Applied when any stage used has fewer than MIN_CALIBRATION_SAMPLES closed
# deals behind its rate.
THIN_SUPPORT_FACTOR = 0.75

_artifact_cache: dict[str, Any] = {}


def _load() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Load calibration and metrics once per process.

    A missing artifact is not an error: a fresh clone has none and must still
    produce a forecast, falling back to `DEFAULT_STAGE_WIN_RATES` with the
    source reported — the same contract as the lead-scoring heuristic.
    """

    if not _artifact_cache:
        calibration = metrics = None
        try:
            if CALIBRATION_PATH.exists():
                calibration = json.loads(CALIBRATION_PATH.read_text())
            if METRICS_PATH.exists():
                metrics = json.loads(METRICS_PATH.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("forecasting artifacts unreadable, falling back to defaults: %s", exc)
        _artifact_cache["calibration"] = calibration
        _artifact_cache["metrics"] = metrics or {}
    return _artifact_cache["calibration"], _artifact_cache["metrics"]


class RevenueForecastingAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        calibration, metrics = _load()
        rates, source, support = features.resolve_win_rates(calibration)

        period = str(input_data["forecast_period"])
        currency = str(input_data.get("currency") or "USD")
        as_of = self._dt(input_data.get("as_of")) or datetime.now().astimezone()
        period_start = self._dt(input_data["period_start"])
        period_end = self._dt(input_data["period_end"])

        buckets = features.classify_deals(
            input_data.get("open_deals") or [],
            period_start=period_start,
            period_end=period_end,
            as_of=as_of,
        )
        weighted, contributions, missing_amount = features.weight_deals(buckets["in_period"], rates)
        committed = Decimal(str(input_data.get("committed_revenue") or "0"))
        # Every money field is quantized to two places, including zero. A
        # response mixing "0" and "50000.00" invites a consumer to parse one of
        # them as an integer.
        weighted = weighted.quantize(Decimal("0.01"))
        committed = committed.quantize(Decimal("0.01"))
        predicted = (committed + weighted).quantize(Decimal("0.01"))

        coverage = self._coverage(len(contributions), missing_amount)
        horizon = self._horizon_periods(period, as_of)
        # Only the stages this pipeline actually uses. Penalising a tenant for
        # the thin support behind a stage none of their deals sit in would make
        # every forecast look weaker than it is.
        stages_used = {c["stage"] for c in contributions}
        weakest_support = min((support.get(s, 0) for s in stages_used), default=0)
        confidence = self._confidence(
            metrics=metrics,
            coverage=coverage,
            weakest_support=weakest_support,
            source=source,
            horizon=horizon,
            stages_used=bool(stages_used),
        )
        warnings = self._warnings(buckets, missing_amount, source, contributions)

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "forecast_period": period,
            "currency": currency,
            # Money leaves this agent as decimal strings: the payload is logged
            # to AIInteractionLog as JSON, and float would reintroduce exactly
            # the representation error `Deal.amount` is NUMERIC to avoid.
            "predicted_revenue": str(predicted),
            "committed_revenue": str(committed),
            "weighted_pipeline": str(weighted),
            "confidence": confidence,
            "calibration_source": source,
            "breakdown": {
                "by_stage": features.by_stage(contributions),
                # The brief's question 3 — "which deals are most likely to
                # close" — which an aggregate regression cannot answer at all.
                "top_deals": sorted(
                    contributions, key=lambda c: Decimal(c["expected_value"]), reverse=True
                )[:10],
                "excluded": {
                    "overdue_deals": len(buckets["overdue"]),
                    "overdue_value": str(self._sum_amounts(buckets["overdue"])),
                    "no_close_date_deals": len(buckets["no_date"]),
                    "no_close_date_value": str(self._sum_amounts(buckets["no_date"])),
                    "missing_amount_deals": missing_amount,
                },
                "trend": self._trend(input_data.get("history") or [], predicted),
                "deal_count": len(contributions),
                "amount_coverage": round(coverage, 3),
                "horizon_periods": horizon,
            },
            "warnings": warnings,
            "explanation": self._explain(
                predicted, committed, weighted, contributions, source, confidence, warnings
            ),
        }

    # ------------------------------------------------------------------ parts

    def _dt(self, value: Any) -> datetime | None:
        if value is None:
            return None
        return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))

    def _sum_amounts(self, deals: list[dict[str, Any]]) -> Decimal:
        total = Decimal("0")
        for deal in deals:
            amount = features.parse_amount(deal.get("amount"))
            if amount is not None:
                total += amount
        return total

    def _coverage(self, priced: int, missing: int) -> float:
        total = priced + missing
        return 1.0 if total == 0 else priced / total

    def _horizon_periods(self, period: str, as_of: datetime) -> int:
        """How many whole months ahead the target period sits."""

        try:
            year, month = (int(part) for part in period.split("-")[:2])
        except ValueError:
            return 0
        return max(0, (year - as_of.year) * 12 + (month - as_of.month))

    def _confidence(
        self,
        *,
        metrics: dict[str, Any],
        coverage: float,
        weakest_support: int,
        source: str,
        horizon: int,
        stages_used: bool,
    ) -> float:
        backtest = (metrics.get("backtest") or {}).get("weighted_pipeline") or {}
        mape = backtest.get("mape")
        if source == "trained" and mape is not None:
            # Measured error on held-out months, not a number chosen to look
            # reassuring. A method that is 20% out historically cannot present
            # as 87% confident today.
            base = min(max(1.0 - float(mape), 0.05), MAX_CONFIDENCE)
        else:
            base = UNCALIBRATED_CONFIDENCE

        factor = coverage
        if source == "trained" and stages_used and weakest_support < features.MIN_CALIBRATION_SAMPLES:
            factor *= THIN_SUPPORT_FACTOR
        factor *= max(HORIZON_DECAY**horizon, MIN_HORIZON_FACTOR)

        return round(min(base * factor, MAX_CONFIDENCE), 3)

    def _trend(self, history: list[dict[str, Any]], predicted: Decimal) -> dict[str, Any]:
        """Change against the last completed period — the dashboard's arrow."""

        if not history:
            return {"previous_period": None, "previous_revenue": None, "change_pct": None}
        last = history[-1]
        previous = Decimal(str(last.get("won_revenue") or "0"))
        change = None if previous == 0 else round(float((predicted - previous) / previous) * 100, 1)
        return {
            "previous_period": last.get("period"),
            "previous_revenue": str(previous),
            "change_pct": change,
        }

    def _warnings(
        self,
        buckets: dict[str, list[dict[str, Any]]],
        missing_amount: int,
        source: str,
        contributions: list[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        if source == "default":
            warnings.append(
                "Stage win rates are untrained defaults, not measured from this workspace's "
                "closed deals — treat the figure as indicative only."
            )
        if missing_amount:
            warnings.append(
                f"{missing_amount} deal(s) in the period have no amount and contribute nothing "
                "to the forecast."
            )
        if buckets["overdue"]:
            warnings.append(
                f"{len(buckets['overdue'])} open deal(s) are past their expected close date and "
                "are excluded — they would otherwise inflate every future period."
            )
        if buckets["no_date"]:
            warnings.append(
                f"{len(buckets['no_date'])} open deal(s) have no expected close date and cannot "
                "be attributed to any period."
            )
        if not contributions:
            warnings.append(
                "No open deal is expected to close in this period, so the forecast is committed "
                "revenue only."
            )
        return warnings

    def _explain(
        self,
        predicted: Decimal,
        committed: Decimal,
        weighted: Decimal,
        contributions: list[dict[str, Any]],
        source: str,
        confidence: float,
        warnings: list[str],
    ) -> str:
        basis = (
            "stage win rates measured from closed-deal history"
            if source == "trained"
            else "conservative default stage win rates (no trained calibration available)"
        )
        text = (
            f"{predicted} = {committed} already won + {weighted} expected from "
            f"{len(contributions)} open deal(s), weighted by {basis}. "
            f"Confidence {confidence} is derived from the method's backtested error and reduced "
            f"for pipeline gaps and forecast horizon — it is not a probability that this exact "
            f"figure is correct."
        )
        if warnings:
            text += " " + " ".join(warnings)
        return text


__all__ = ["MODEL_NAME", "MODEL_VERSION", "RevenueForecastingAgent"]
