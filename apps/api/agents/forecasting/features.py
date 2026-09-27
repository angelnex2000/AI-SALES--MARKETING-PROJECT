"""Aggregation and calibration for revenue forecasting.

## Why this is not a regression over monthly rows

The module brief specifies an XGBoost regressor over one row per month. The
historical CRM spans 2023-01 to 2026-07, which is **43 rows**. A gradient
boosting model with a dozen engineered features on 43 examples does not learn a
trend, it memorises one; a temporal split leaves roughly nine test points, so
the reported error is itself noise.

Worse, the failure is directional. **Tree ensembles cannot extrapolate**: a
prediction is the mean of the training rows in a leaf, so once pipeline value
grows beyond anything in the training range the forecast flattens at the
historical maximum. For a growing business that produces a confidently low
number every single month, which is the one error a revenue forecast must not
make quietly.

So the primary estimator is **weighted pipeline**: for each open deal, its
amount multiplied by the historically measured probability that a deal in its
stage is won. This is still "aggregated business signals, not individual
leads" — the brief's own closing principle — because the weights come from
aggregate history (44,574 closed deals, not 43 months) and the deals are summed
into a pipeline total. What changes is that the arithmetic is arithmetic
instead of a fit, which means it extrapolates correctly, survives a quarter
with no analogue in history, and can answer the brief's own question 3,
"which deals are most likely to close" — something an aggregate regression
structurally cannot.

`train.py` still fits and backtests a monthly trend model, and reports both,
so the choice above is a measurement rather than an assertion.

## Money

Every amount here is `Decimal`. `Deal.amount` is `NUMERIC(14,2)` precisely
because these values are summed across a whole pipeline, and binary floating
point cannot represent 0.10 — the error compounds per deal, and this is the
number a CEO quotes in a board meeting.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

# Fallback P(win | stage) for a workspace with no trained calibration. Ordered
# the way the pipeline is: a deal in negotiation is likelier to close than one
# that was created yesterday. Deliberately conservative — a fresh workspace
# should under-promise rather than report a confident number nobody measured.
#
# `train.py` overwrites these from real closed-deal history; the agent reports
# which source it used, because a forecast built on guessed weights and one
# built on 44k closed deals must not look identical.
DEFAULT_STAGE_WIN_RATES: dict[str, float] = {
    "new": 0.05,
    "qualified": 0.15,
    "demo_scheduled": 0.30,
    "proposal_sent": 0.45,
    "negotiation": 0.65,
    "closed_won": 1.0,
    "closed_lost": 0.0,
}

# Below this many closed deals behind a stage, its rate is a small-sample
# artifact rather than a measurement, and confidence is reduced accordingly.
MIN_CALIBRATION_SAMPLES = 30

# Stages that are already resolved — they contribute banked revenue, not
# probability-weighted pipeline.
CLOSED_STAGES: tuple[str, ...] = ("closed_won", "closed_lost")


def resolve_win_rates(
    calibration: dict[str, Any] | None,
) -> tuple[dict[str, float], str, dict[str, int]]:
    """Return (rates, source, support-per-stage).

    `source` is reported all the way out to the API response. A number derived
    from `DEFAULT_STAGE_WIN_RATES` is a guess with a decimal point on it, and
    presenting it beside one calibrated on real history — with no way to tell
    them apart — is how a plausible forecast becomes an unchallenged one.

    Support is returned per stage rather than as a single worst case so the
    caller can penalise only the stages a given pipeline actually uses. The
    training CRM has no `demo_scheduled` analogue, so that stage always has
    zero support; a tenant with no deals in it should not be penalised for a
    rate their forecast never touched.
    """

    if not calibration or not calibration.get("rates"):
        return dict(DEFAULT_STAGE_WIN_RATES), "default", {}

    rates = {**DEFAULT_STAGE_WIN_RATES, **{k: float(v) for k, v in calibration["rates"].items()}}
    support = {str(k): int(v) for k, v in (calibration.get("support") or {}).items()}
    return rates, "trained", support


def parse_amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None


def classify_deals(
    open_deals: list[dict[str, Any]], *, period_start: datetime, period_end: datetime, as_of: datetime
) -> dict[str, list[dict[str, Any]]]:
    """Split the open pipeline into what can and cannot be forecast.

    Three buckets exist because each is a different message to a manager, and
    collapsing them produces a number that is wrong in a way nobody can see:

      * `in_period` — expected to close inside the window. The forecast.
      * `overdue` — still open, but its expected close date has already passed.
        Excluded, and reported. Counting them silently inflates every month's
        forecast with deals that already missed their date once, and they are
        the single largest source of optimistic bias in hand-built forecasts.
      * `no_date` — no expected close date at all, so it cannot be attributed
        to any period. Excluded, and reported: a pipeline where most deals lack
        a date produces a small forecast that reads as a collapse rather than
        as missing data.
    """

    buckets: dict[str, list[dict[str, Any]]] = {"in_period": [], "overdue": [], "no_date": []}
    for deal in open_deals:
        if str(deal.get("stage")) in CLOSED_STAGES:
            continue
        close = deal.get("expected_close_date")
        if close is None:
            buckets["no_date"].append(deal)
            continue
        moment = close if isinstance(close, datetime) else datetime.fromisoformat(str(close))
        if moment < as_of and moment < period_start:
            buckets["overdue"].append(deal)
        elif period_start <= moment < period_end:
            buckets["in_period"].append(deal)
    return buckets


def weight_deals(
    deals: list[dict[str, Any]], rates: dict[str, float]
) -> tuple[Decimal, list[dict[str, Any]], int]:
    """Expected value of a set of deals: Σ amount × P(win | stage).

    Returns (total, per-deal contributions, count missing an amount). A deal
    with no amount contributes nothing and is counted — it is real pipeline the
    forecast cannot see, and that gap belongs in `confidence`, not hidden in a
    sum.
    """

    total = Decimal("0")
    contributions: list[dict[str, Any]] = []
    missing_amount = 0

    for deal in deals:
        amount = parse_amount(deal.get("amount"))
        if amount is None:
            missing_amount += 1
            continue
        stage = str(deal.get("stage"))
        rate = rates.get(stage, DEFAULT_STAGE_WIN_RATES["new"])
        expected = (amount * Decimal(str(rate))).quantize(Decimal("0.01"))
        total += expected
        contributions.append(
            {
                "deal_id": str(deal.get("id") or deal.get("deal_id") or ""),
                "name": deal.get("name"),
                "stage": stage,
                "amount": str(amount),
                "win_rate": round(rate, 4),
                "expected_value": str(expected),
            }
        )

    return total, contributions, missing_amount


def by_stage(contributions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-stage rollup — the "forecast breakdown" the dashboard renders."""

    grouped: dict[str, dict[str, Any]] = {}
    for item in contributions:
        row = grouped.setdefault(
            item["stage"],
            {
                "stage": item["stage"],
                "deal_count": 0,
                "pipeline_value": Decimal("0"),
                "expected_value": Decimal("0"),
                "win_rate": item["win_rate"],
            },
        )
        row["deal_count"] += 1
        row["pipeline_value"] += Decimal(item["amount"])
        row["expected_value"] += Decimal(item["expected_value"])

    return [
        {**row, "pipeline_value": str(row["pipeline_value"]), "expected_value": str(row["expected_value"])}
        for row in sorted(grouped.values(), key=lambda r: r["win_rate"], reverse=True)
    ]


# --------------------------------------------------------------- trend model

# Features for the monthly regression that `train.py` fits and backtests as a
# comparison. Named here so training and any future inference build the same
# vector — the train/serve skew rule from `lead_scoring/features.py`.
MONTHLY_FEATURE_NAMES: tuple[str, ...] = (
    "won_revenue_lag_1",
    "won_revenue_lag_2",
    "won_revenue_lag_3",
    "won_count_lag_1",
    "rolling_mean_3",
    "month_of_year",
    "quarter",
)


def monthly_features(history: list[dict[str, Any]], index: int) -> list[float] | None:
    """Feature vector for the month at `history[index]`, from prior months only.

    Returns None when there is insufficient lag history. Every value is a lag
    or a calendar fact: using the target month's own pipeline or deal counts
    would leak, because those are only known once the month is over — the same
    trap `lead_scoring/features.py::LEAKING_FIELDS` guards against.
    """

    if index < 3:
        return None
    lags = [float(history[index - k]["won_revenue"]) for k in (1, 2, 3)]
    period = str(history[index]["period"])
    month = int(period.split("-")[1])
    return [
        *lags,
        float(history[index - 1]["won_count"]),
        sum(lags) / 3.0,
        float(month),
        float((month - 1) // 3 + 1),
    ]
