"""Feature engineering for lead scoring.

**One transformation, shared by training and inference.** This module is
imported by `train.py` and by `model.py`; neither builds a vector any other
way. Train/serve skew — a scaler fitted differently, a category encoded in a
different order — produces a model that scores well offline and badly in
production, with nothing in the logs to explain why.

## Which features are allowed

Only what is known **at the moment we score**, which for this product is
pre-Gate-1: a lead has just arrived and nobody has contacted it. That rules
out several features the obvious design reaches for:

* `stage`, `probability`, `forecast_category`, `sales_cycle_days` — set after
  the outcome. In the training CRM, `stage` separates the label perfectly
  (Closed Won → 100% won, Closed Lost → 0% won). A model using it reports
  ~1.00 AUC and is worthless: it has learned to read the answer.
* meetings held, emails opened, replies received — these are *consequences of
  working a lead*, not properties of it. They are zero for every lead a rep is
  deciding whether to call, so a model trained on them has never seen the
  distribution it is asked to predict on. It learns "leads that were already
  engaged convert" — true, useless, and self-fulfilling: the reps' existing
  prioritisation becomes the model's ground truth and it recommends exactly
  the leads they already work.

What remains is firmographics and origin — what is actually knowable about a
cold lead.
"""

import math
from typing import Any

# Categorical levels are frozen here rather than inferred from whatever data a
# run happens to see. An encoder fitted per-run assigns different column
# positions when a rare industry is absent from a batch, silently shifting
# every weight downstream of it.
INDUSTRIES: tuple[str, ...] = (
    "automotive",
    "biotech & pharma",
    "construction",
    "education",
    "energy & utilities",
    "financial services",
    "government & public sector",
    "healthcare",
    "hospitality",
    "logistics & transportation",
    "manufacturing",
    "media & entertainment",
    "non-profit",
    "professional services",
    "real estate",
    "retail & e-commerce",
    "software & saas",
    "telecommunications",
)

# These levels must match the source data exactly. `lead_source` is the single
# strongest predictor in the historical CRM — customer referrals convert at
# 43% against cold email's 17% — so a mismatched level name silently collapses
# the best signal the model has into the `other` bucket. That is not
# hypothetical: an earlier version of this list was written from memory and
# cost roughly 0.09 AUC.
LEAD_SOURCES: tuple[str, ...] = (
    "cold email",
    "customer referral",
    "event / conference",
    "inbound - content download",
    "inbound - web form",
    "outbound - sdr",
    "paid search",
    "partner referral",
)

TIERS: tuple[str, ...] = ("enterprise", "mid-market", "smb")

FEATURE_NAMES: tuple[str, ...] = (
    *(f"industry={i}" for i in INDUSTRIES),
    "industry=other",
    *(f"source={s}" for s in LEAD_SOURCES),
    "source=other",
    *(f"tier={t}" for t in TIERS),
    "tier=other",
    "log_employees",
    "log_revenue",
    "has_employees",
    "has_revenue",
    "has_campaign",
)


def _one_hot(value: str | None, levels: tuple[str, ...]) -> list[float]:
    """One-hot with an explicit `other` bucket.

    The trailing slot matters: an unseen industry at inference must land
    somewhere deliberate rather than producing an all-zero block, which the
    model reads as "every industry is absent" — a state it never saw in
    training.
    """

    normalised = (value or "").strip().lower()
    encoded = [1.0 if normalised == level else 0.0 for level in levels]
    encoded.append(0.0 if normalised in levels else 1.0)
    return encoded


def _log_scale(value: float | None, *, cap: float) -> tuple[float, float]:
    """Return `(scaled_value, present_flag)`.

    Log because headcount and revenue span orders of magnitude — left linear,
    one 500,000-employee company dominates the gradient. The presence flag
    keeps "unknown" distinguishable from "zero": a lead with no headcount
    recorded is not a company with no staff, and collapsing the two teaches
    the model that missing data means tiny.
    """

    if value is None or value <= 0:
        return 0.0, 0.0
    return min(math.log10(value) / cap, 1.0), 1.0


def build_features(lead: dict[str, Any]) -> list[float]:
    """Turn a lead-shaped dict into the model's input vector.

    Takes the same keys whether the dict came from our `Lead` table or from a
    row of the training CRM — which is what keeps the two paths honest.
    """

    log_employees, has_employees = _log_scale(lead.get("employees"), cap=6.0)
    log_revenue, has_revenue = _log_scale(lead.get("annual_revenue"), cap=10.0)

    return [
        *_one_hot(lead.get("industry"), INDUSTRIES),
        *_one_hot(lead.get("lead_source"), LEAD_SOURCES),
        *_one_hot(lead.get("account_tier"), TIERS),
        log_employees,
        log_revenue,
        has_employees,
        has_revenue,
        1.0 if lead.get("campaign_id") else 0.0,
    ]


def describe_features(vector: list[float]) -> dict[str, float]:
    """Name the active features, for explainability (Module 6) and debugging."""

    return {name: value for name, value in zip(FEATURE_NAMES, vector, strict=True) if value != 0.0}


FEATURE_COUNT = len(FEATURE_NAMES)

# Never usable as features — kept as a named list so training code can assert
# against it rather than relying on someone remembering.
LEAKING_FIELDS: frozenset[str] = frozenset(
    {
        "stage",
        "probability",
        "forecast_category",
        "sales_cycle_days",
        "is_closed",
        "is_won",
        "loss_reason",
        "actual_close_date",
        "meetings_completed",
        "emails_opened",
        "replies_received",
        "activity_count",
    }
)
