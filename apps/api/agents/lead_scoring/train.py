"""Train the lead-scoring model.

    python -m agents.lead_scoring.train --db ../../data/crm.db

Trains a gradient-boosted classifier on the historical CRM and writes
`artifacts/lead_scoring.joblib` plus a metrics sidecar.

## Why gradient boosting rather than a neural network

The course material specifies a PyTorch MLP. For this problem that is the
wrong tool three times over:

1. **The data is small, tabular and mostly categorical** — ~45k rows and
   ~30 features. Gradient-boosted trees beat MLPs on exactly this shape, and
   need no scaling, no learning-rate search, and no epoch tuning.
2. **Explainability is the next module.** A tree ensemble exposes real feature
   importances and per-prediction attribution; an MLP needs a separate
   approximation layer (SHAP/LIME) to say anything about *why* a lead scored
   94.
3. **torch is 800MB–2.5GB in the image**, and the same trade-off was already
   declined for embeddings in Module 4. `scikit-learn` is already a dependency
   and is listed in `requirements.txt` for precisely this agent.

## Temporal split, not random

Deals are split by `created_date`, training on the past and validating on the
future. A random split leaks: deals from the same account, campaign and period
land on both sides, and the model gets credit for recognising accounts it has
already seen rather than for generalising to new ones. Random-split AUC on
this data flatters the model and would not survive contact with next quarter.
"""

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from agents.lead_scoring.features import (
    FEATURE_NAMES,
    LEAKING_FIELDS,
    build_features,
)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "lead_scoring.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

MODEL_NAME = "lead_scoring"
MODEL_VERSION = "lead-scoring-gbdt-v1"

LABEL_COLUMN = "is_won"

# Only fields knowable when a lead arrives. Every column excluded here is
# excluded for a reason recorded in features.py.
QUERY = """
SELECT
    d.deal_id,
    d.created_date,
    d.lead_source,
    d.campaign_id,
    a.industry,
    a.account_tier,
    a.employee_count,
    a.annual_revenue,
    d.is_won
FROM deals d
JOIN accounts a ON a.account_id = d.account_id
WHERE d.is_closed = 1
ORDER BY d.created_date
"""


def load_rows(db_path: Path) -> list[dict[str, Any]]:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in con.execute(QUERY)]
    finally:
        con.close()

    # The label itself is selected on purpose; everything else post-outcome is
    # a leak. A loud failure beats a suspiciously good AUC, so if someone
    # widens the query later this stops it at training time.
    leaked = (LEAKING_FIELDS - {LABEL_COLUMN}) & set(rows[0]) if rows else set()
    assert not leaked, f"query selects post-outcome fields as features: {sorted(leaked)}"
    return rows


def to_xy(rows: list[dict[str, Any]]) -> tuple[list[list[float]], list[int]]:
    features = [
        build_features(
            {
                "industry": row["industry"],
                "lead_source": row["lead_source"],
                "account_tier": row["account_tier"],
                "employees": row["employee_count"],
                "annual_revenue": row["annual_revenue"],
                "campaign_id": row["campaign_id"],
            }
        )
        for row in rows
    ]
    labels = [int(row["is_won"]) for row in rows]
    return features, labels


def temporal_split(rows: list[dict[str, Any]], holdout: float = 0.2) -> tuple[list, list]:
    """Past for training, future for validation — rows arrive date-ordered."""

    cut = int(len(rows) * (1 - holdout))
    return rows[:cut], rows[cut:]


def _lift_metrics(labels: list[int], probabilities, base_rate: float) -> dict[str, float]:
    """Conversion rate within the top-scored decile, versus the base rate.

    This is the number that decides whether the model is worth shipping: a rep
    works a queue top-down, so "leads in your top 10% convert 1.8x more often
    than average" is actionable in a way that AUC is not.
    """

    ranked = sorted(zip(probabilities, labels, strict=True), key=lambda p: p[0], reverse=True)
    metrics: dict[str, float] = {}
    for fraction in (0.1, 0.2):
        cut = max(1, int(len(ranked) * fraction))
        top = ranked[:cut]
        rate = sum(label for _, label in top) / len(top)
        key = int(fraction * 100)
        metrics[f"conversion_rate_top_{key}pct"] = round(rate, 4)
        metrics[f"lift_top_{key}pct"] = round(rate / base_rate, 3) if base_rate else 0.0
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="path to crm.db")
    parser.add_argument("--holdout", type=float, default=0.2)
    args = parser.parse_args()

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import (
        average_precision_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    rows = load_rows(args.db)
    train_rows, test_rows = temporal_split(rows, args.holdout)
    x_train, y_train = to_xy(train_rows)
    x_test, y_test = to_xy(test_rows)

    base_rate = sum(y_test) / len(y_test)
    print(f"train={len(x_train)}  test={len(x_test)}  test base rate={base_rate:.3f}")

    model = HistGradientBoostingClassifier(
        max_iter=200,
        learning_rate=0.05,
        max_depth=6,
        l2_regularization=1.0,
        random_state=42,
    )
    model.fit(x_train, y_train)
    probabilities = model.predict_proba(x_test)[:, 1]
    predictions = (probabilities >= 0.5).astype(int)

    metrics = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now().astimezone().isoformat(),
        "rows_train": len(x_train),
        "rows_test": len(x_test),
        "test_base_rate": round(base_rate, 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        # More honest than AUC on an imbalanced problem: the baseline for
        # average precision is the base rate, so it is obvious whether the
        # model beats "guess the prior".
        "average_precision": round(float(average_precision_score(y_test, probabilities)), 4),
        # Reported for completeness, but a 0.5 cutoff is close to meaningless
        # here: the base rate is ~30%, so the model rarely crosses it and
        # recall looks catastrophic. Nobody uses this model as a yes/no
        # classifier — it ranks a queue.
        "precision_at_0.5": round(float(precision_score(y_test, predictions, zero_division=0)), 4),
        "recall_at_0.5": round(float(recall_score(y_test, predictions, zero_division=0)), 4),
        "f1_at_0.5": round(float(f1_score(y_test, predictions, zero_division=0)), 4),
        # The metric that answers the actual business question: if a rep works
        # the top 10% of the queue, how much better than random is that?
        **_lift_metrics(y_test, probabilities, base_rate),
        "feature_names": list(FEATURE_NAMES),
        "split": "temporal",
    }

    if metrics["roc_auc"] > 0.95:
        # Nothing about cold firmographics predicts conversion this well.
        # An AUC this high means a post-outcome column crept into the query.
        print("\n  WARNING: AUC > 0.95 on firmographics alone strongly suggests label leakage.\n")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    import joblib

    joblib.dump({"model": model, "feature_names": list(FEATURE_NAMES)}, MODEL_PATH)
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    print(json.dumps(metrics, indent=2))
    print(f"\nwrote {MODEL_PATH}")


if __name__ == "__main__":
    main()
