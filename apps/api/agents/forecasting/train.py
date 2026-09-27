"""Calibrate and backtest the revenue forecast.

    python -m agents.forecasting.train --db ../../data/crm.db

Writes `artifacts/stage_win_rates.json` and `artifacts/metrics.json`.
Artifacts are gitignored, so a fresh clone forecasts from
`features.DEFAULT_STAGE_WIN_RATES` and reports `calibration_source: default`.

## What this dataset can and cannot calibrate

The historical CRM keeps only a deal's **current** stage. Once a deal closes,
`stage` becomes "Closed Won"/"Closed Lost" and whatever it was the week before
is gone — there is no stage-history table. So `P(win | stage = proposal_sent)`
is **not measurable here**, and any script claiming to have measured it is
reading `probability` or `forecast_category`, which are set post-outcome and
leak the label (the same trap `lead_scoring/features.py::LEAKING_FIELDS`
documents).

What is measurable, point-in-time and leak-free, is the **overall win rate**
from deals closed before a given date. So the calibration splits the two:

  * the *shape* across stages stays a business prior (a negotiation is likelier
    to close than a prospect), and
  * the *level* is rescaled so the pipeline-weighted average matches the
    measured overall win rate.

Recorded as `method: "prior_shape_measured_level"` in the artifact so nobody
later mistakes it for a per-stage measurement.

## Why the backtest matters more than the fit

`model.py` derives its reported confidence from the backtest MAPE below. That
is the only reason the number means anything: it is this method's measured
error on months it had not seen, not a value chosen because it looked
reassuring.

The monthly GBDT the brief asks for is trained and scored here **as a
comparison**, on all 43 available rows, so the decision to use weighted
pipeline instead is a measurement rather than an opinion.
"""

import argparse
import json
import math
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from agents.forecasting import features

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
CALIBRATION_PATH = ARTIFACT_DIR / "stage_win_rates.json"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

MODEL_VERSION = "revenue-weighted-pipeline-v1"

# The training CRM's stage vocabulary is not ours. Mapped explicitly rather
# than by lowercasing — an unmapped level silently becomes the lowest-weight
# bucket, which is exactly how `lead_scoring` lost ~0.09 AUC by writing
# `LEAD_SOURCES` from memory.
#
# Note there is **no analogue for `demo_scheduled`** in this dataset. Its rate
# stays the interpolated prior with zero support, which trips
# `THIN_SUPPORT_FACTOR` in the agent — correct, since nothing measured it.
STAGE_MAP: dict[str, str] = {
    "Prospecting": "new",
    "Qualification": "qualified",
    "Proposal": "proposal_sent",
    "Negotiation": "negotiation",
    "Closed Won": "closed_won",
    "Closed Lost": "closed_lost",
}

# Months held out for the backtest, taken from the end of the series.
HOLDOUT_MONTHS = 12
# Ignore the ramp-up at the start of a synthetic series: 14 won deals in the
# first month against 700 in the last is not seasonality, it is the generator
# warming up, and including it flatters every trend model.
WARMUP_MONTHS = 6


def _month(value: str | None) -> str | None:
    return value[:7] if value else None


def load_deals(db_path: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT deal_id, stage, amount, created_date, expected_close_date,
               actual_close_date, is_closed, is_won
        FROM deals
        WHERE amount IS NOT NULL AND created_date IS NOT NULL
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def monthly_history(deals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Actual won revenue and count per month — the target series."""

    revenue: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for deal in deals:
        if deal["is_won"] and deal["actual_close_date"]:
            period = _month(deal["actual_close_date"])
            revenue[period] += float(deal["amount"])
            counts[period] += 1
    periods = sorted(revenue)
    return [
        {"period": p, "won_revenue": revenue[p], "won_count": counts[p]} for p in periods
    ]


def measured_win_rate(deals: list[dict[str, Any]], *, before: str) -> tuple[float, int]:
    """Win rate over deals closed strictly before `before` (YYYY-MM).

    Point-in-time: a backtest for August must not know how July's deals turned
    out after August began, and must certainly not know about September.
    """

    won = closed = 0
    for deal in deals:
        period = _month(deal["actual_close_date"])
        if not deal["is_closed"] or not period or period >= before:
            continue
        closed += 1
        won += int(bool(deal["is_won"]))
    return (won / closed if closed else 0.0), closed


def rescale_rates(overall: float, open_stage_counts: dict[str, int]) -> dict[str, float]:
    """Keep the prior's shape, move its level onto the measured win rate.

    Without this the defaults would forecast whatever they were written to
    forecast. With it, a workspace whose deals genuinely close at 12% gets a
    forecast scaled to 12% while a negotiation still outranks a prospect.
    """

    prior = {
        stage: rate
        for stage, rate in features.DEFAULT_STAGE_WIN_RATES.items()
        if stage not in features.CLOSED_STAGES
    }
    total = sum(open_stage_counts.get(stage, 0) for stage in prior)
    if not total or overall <= 0:
        return dict(features.DEFAULT_STAGE_WIN_RATES)

    prior_mean = sum(prior[s] * open_stage_counts.get(s, 0) for s in prior) / total
    factor = overall / prior_mean if prior_mean else 1.0
    rescaled = {s: min(round(r * factor, 4), 0.95) for s, r in prior.items()}
    return {**rescaled, "closed_won": 1.0, "closed_lost": 0.0}


def backtest_weighted_pipeline(
    deals: list[dict[str, Any]], periods: list[str], actuals: dict[str, float]
) -> tuple[list[float], list[float]]:
    """Replay the forecast for each held-out month using only prior data.

    The pipeline is reconstructed as it stood on the first of the month: deals
    created before it, not yet closed, expected to close inside it. Stage is
    deliberately not used — the dataset does not retain a closed deal's
    pre-close stage, so using today's stage would be reading the answer.
    """

    predicted: list[float] = []
    observed: list[float] = []
    for period in periods:
        rate, _ = measured_win_rate(deals, before=period)
        total = 0.0
        for deal in deals:
            created = _month(deal["created_date"])
            closed = _month(deal["actual_close_date"])
            expected = _month(deal["expected_close_date"])
            if created is None or created >= period:
                continue
            if closed is not None and closed < period:
                continue
            if expected != period:
                continue
            total += float(deal["amount"]) * rate
        predicted.append(total)
        observed.append(actuals.get(period, 0.0))
    return predicted, observed


def regression_metrics(predicted: list[float], observed: list[float]) -> dict[str, float]:
    n = len(observed)
    if not n:
        return {}
    errors = [p - o for p, o in zip(predicted, observed, strict=True)]
    mean = sum(observed) / n
    ss_tot = sum((o - mean) ** 2 for o in observed)
    ss_res = sum(e**2 for e in errors)
    mape = [abs(e) / o for e, o in zip(errors, observed, strict=True) if o]
    return {
        "months": n,
        "mae": round(sum(abs(e) for e in errors) / n, 2),
        "rmse": round(math.sqrt(ss_res / n), 2),
        "mape": round(sum(mape) / len(mape), 4) if mape else None,
        "r2": round(1 - ss_res / ss_tot, 4) if ss_tot else None,
    }


def baseline_last_month(history: list[dict[str, Any]], start: int) -> tuple[list[float], list[float]]:
    predicted = [history[i - 1]["won_revenue"] for i in range(start, len(history))]
    observed = [history[i]["won_revenue"] for i in range(start, len(history))]
    return predicted, observed


def gbdt_trend(history: list[dict[str, Any]], start: int) -> dict[str, Any]:
    """The brief's monthly regressor, measured rather than assumed.

    scikit-learn's GBDT rather than XGBoost, for the reason `lead_scoring`
    already settled: it is in `requirements.txt`, and adding a dependency to
    fit 43 rows is not a trade worth making.
    """

    from sklearn.ensemble import GradientBoostingRegressor

    rows = [
        (features.monthly_features(history, i), history[i]["won_revenue"])
        for i in range(len(history))
    ]
    usable = [(x, y) for x, y in rows if x is not None]
    train = [(x, y) for i, (x, y) in enumerate(usable) if i + 3 < start]
    test = [(x, y) for i, (x, y) in enumerate(usable) if i + 3 >= start]
    if len(train) < 8 or not test:
        return {"skipped": "not enough monthly rows to fit and hold out"}

    model = GradientBoostingRegressor(random_state=0, n_estimators=200, max_depth=2)
    model.fit([x for x, _ in train], [y for _, y in train])
    predicted = list(model.predict([x for x, _ in test]))
    observed = [y for _, y in test]
    return {
        **regression_metrics(predicted, observed),
        "train_months": len(train),
        "note": (
            "Trained on the monthly series the brief specifies. Tree ensembles predict the mean "
            "of a training leaf, so they cannot extrapolate above the largest month they saw — "
            "compare the errors against the weighted-pipeline row before using this."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="path to the historical CRM SQLite")
    parser.add_argument("--holdout", type=int, default=HOLDOUT_MONTHS)
    args = parser.parse_args()

    deals = load_deals(args.db)
    history = monthly_history(deals)[WARMUP_MONTHS:]
    if len(history) <= args.holdout + 4:
        raise SystemExit(f"only {len(history)} usable months — not enough to hold out {args.holdout}")

    actuals = {row["period"]: row["won_revenue"] for row in history}
    holdout_periods = [row["period"] for row in history[-args.holdout :]]
    start = len(history) - args.holdout

    # --- calibration, fitted on everything before the holdout
    cutoff = holdout_periods[0]
    overall, support = measured_win_rate(deals, before=cutoff)
    open_stage_counts: dict[str, int] = defaultdict(int)
    for deal in deals:
        if not deal["is_closed"]:
            open_stage_counts[STAGE_MAP.get(deal["stage"], "new")] += 1
    rates = rescale_rates(overall, open_stage_counts)

    # --- evaluation
    predicted, observed = backtest_weighted_pipeline(deals, holdout_periods, actuals)
    results = {
        "weighted_pipeline": regression_metrics(predicted, observed),
        "baseline_last_month": regression_metrics(*baseline_last_month(history, start)),
        "gbdt_monthly_trend": gbdt_trend(history, start),
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    CALIBRATION_PATH.write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "method": "prior_shape_measured_level",
                "measured_overall_win_rate": round(overall, 4),
                "rates": rates,
                # Support is the closed-deal count behind the *level*. Per-stage
                # support is 0 because the dataset retains no pre-close stage —
                # which is what keeps the agent's thin-support penalty honest.
                "support": {stage: (support if stage != "demo_scheduled" else 0) for stage in rates},
                "trained_before_period": cutoff,
            },
            indent=2,
        )
    )
    METRICS_PATH.write_text(
        json.dumps(
            {
                "model_version": MODEL_VERSION,
                "months_available": len(history),
                "holdout_months": args.holdout,
                "backtest": results,
            },
            indent=2,
        )
    )

    print(f"months available: {len(history)} (after {WARMUP_MONTHS}-month warm-up trim)")
    print(f"measured overall win rate: {overall:.4f} from {support} closed deals")
    print(f"calibrated rates: {rates}")
    for name, metrics in results.items():
        print(f"  {name}: {metrics}")
    print(f"wrote {CALIBRATION_PATH.name} and {METRICS_PATH.name}")


if __name__ == "__main__":
    main()
