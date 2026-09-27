"""Explains a lead score.

## The rule that matters: explanations are derived, never computed in parallel

The obvious design writes a second set of business rules —

    if icp_score >= 90: positives.append("Excellent ICP match")

— and that is worse than no explanation at all, because the two can disagree.
A lead can trip "Excellent ICP match" while the model scored it 40, and the
page then shows a low number above a glowing reason. The rep concludes the AI
is broken, which is the exact opposite of what an explainability feature is
for.

Worse, hand-written rules can cite things the model never saw. The course
material's example negative factor — "No previous customer reply" — is a
feature deliberately **excluded** from the model (see
`lead_scoring/features.py`: engagement counts are zero for every lead a rep is
deciding whether to call). Listing it as a reason for the score would be a
plain falsehood.

So every factor here comes from one of two places, both traceable to the
actual prediction:

* **Measured model attribution.** The lead is re-scored with one feature group
  neutralised; the drop or rise *is* that group's contribution. This is exact
  for the model — not an approximation like SHAP — and needs no extra
  dependency. It costs one `predict_proba` per group, on a handful of groups.
* **Exact score components.** The ICP and signal adjustments are arithmetic
  terms of the composed score, so their contribution is known precisely.
"""

from typing import Any

from agents.explainability.schemas import Factor, FactorSource, ScoreExplanation
from agents.lead_scoring import model as scoring
from agents.lead_scoring.features import build_features

# Feature groups worth explaining, mapped to the lead keys that produce them.
# Grouped rather than per-column because "industry" is 19 one-hot columns and
# a rep needs one line, not nineteen.
FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "industry": ("industry",),
    "lead source": ("lead_source",),
    "company size": ("employees",),
    "revenue": ("annual_revenue",),
    "account tier": ("account_tier",),
}

# Below this many points a factor is noise and clutters the card.
MIN_IMPACT = 1.0


def _readable(group: str, lead: dict[str, Any], positive: bool) -> str:
    value = lead.get(FEATURE_GROUPS[group][0])
    if value is None or value == "":
        return f"No {group} recorded"
    if group == "company size":
        return f"Company size ({value:,} employees)" if isinstance(value, int) else f"Company size ({value})"
    if group == "revenue":
        return f"Annual revenue (~{value:,.0f})" if isinstance(value, int | float) else f"Revenue ({value})"
    qualifier = "" if positive else " (below average for conversions)"
    return f"{str(value).title()} {group}{qualifier}"


def attribute_model_score(lead: dict[str, Any]) -> tuple[float, list[Factor]]:
    """Measure each feature group's contribution by ablation.

    Returns `(baseline_probability, factors)`. The baseline is the model's
    prediction for a lead with none of these attributes known — the reference
    point that makes "+8 for industry" mean something.
    """

    model, _ = scoring._load()
    if model is None:
        # Untrained fallback: the heuristic reads only lead_source, so that is
        # the only honest thing to attribute.
        return 0.0, []

    def probability(payload: dict[str, Any]) -> float:
        return float(model.predict_proba([build_features(payload)])[0][1])

    full = probability(lead)
    blank = probability({})

    factors: list[Factor] = []
    for group, keys in FEATURE_GROUPS.items():
        if all(lead.get(key) in (None, "") for key in keys):
            continue
        ablated = {k: v for k, v in lead.items() if k not in keys}
        impact = (full - probability(ablated)) * 100
        if abs(impact) < MIN_IMPACT:
            continue
        factors.append(
            Factor(
                label=_readable(group, lead, positive=impact > 0),
                impact=round(impact, 1),
                source=FactorSource.MODEL,
                detail=f"{group}={lead.get(keys[0])}",
            )
        )
    return blank * 100, factors


def explain(*, score_output: dict[str, Any], lead: dict[str, Any]) -> ScoreExplanation:
    """Build the full explanation from a `LeadScoringAgent` result."""

    components = score_output.get("components") or {}
    baseline, factors = attribute_model_score(lead)

    icp_adjustment = float(components.get("icp_adjustment") or 0.0)
    if abs(icp_adjustment) >= MIN_IMPACT:
        factors.append(
            Factor(
                label=(
                    "Strong match for your ideal customer profile"
                    if icp_adjustment > 0
                    else "Weak match for your ideal customer profile"
                ),
                impact=round(icp_adjustment, 1),
                source=FactorSource.COMPONENT,
                detail="icp_adjustment",
            )
        )

    signal_adjustment = float(components.get("signal_adjustment") or 0.0)
    if signal_adjustment >= MIN_IMPACT:
        factors.append(
            Factor(
                label="Recent buying signals detected",
                impact=round(signal_adjustment, 1),
                source=FactorSource.COMPONENT,
                detail="signal_adjustment",
            )
        )

    positives = sorted([f for f in factors if f.impact > 0], key=lambda f: -f.impact)
    negatives = sorted([f for f in factors if f.impact < 0], key=lambda f: f.impact)

    score = int(score_output.get("score") or 0)
    return ScoreExplanation(
        lead_score=score,
        confidence=float(score_output.get("confidence") or 0.0),
        baseline_score=round(baseline),
        positive_factors=positives,
        negative_factors=negatives,
        recommendation=recommend(score_output),
        model_version=str(score_output.get("model_version") or "unknown"),
        summary=_summary(score, positives, negatives, float(score_output.get("confidence") or 0.0)),
    )


def recommend(score_output: dict[str, Any]) -> str:
    """What the rep should do next.

    Deliberately conditioned on **confidence as well as score**: recommending
    action off a model that barely discriminates is how a team learns to
    distrust the whole product. With the current model (AUC 0.62) confidence
    is ~0.24, so the wording stays advisory rather than instructive.
    """

    score = int(score_output.get("score") or 0)
    confidence = float(score_output.get("confidence") or 0.0)
    components = score_output.get("components") or {}
    has_signals = float(components.get("signal_adjustment") or 0.0) > 0

    if confidence < 0.2:
        return (
            "Review manually — the scoring model is not yet confident enough "
            "to prioritise on its own."
        )
    if score >= 70 and has_signals:
        return "Contact now — good fit with active buying signals. Generate personalised outreach."
    if score >= 70:
        return "Good fit. Generate personalised outreach when capacity allows."
    if score >= 40:
        return "Moderate fit. Research further before investing time."
    return "Low priority. Consider a nurture campaign rather than direct outreach."


def _summary(score: int, positives: list[Factor], negatives: list[Factor], confidence: float) -> str:
    if not positives and not negatives:
        return (
            f"Score {score}/100. No individual attribute moved the score "
            "meaningfully — this lead looks average on every dimension we measure."
        )
    lead_reason = positives[0].label if positives else negatives[0].label
    parts = [f"Score {score}/100, driven mainly by: {lead_reason.lower()}."]
    if negatives and positives:
        parts.append(f"Held back by: {negatives[0].label.lower()}.")
    if confidence < 0.3:
        parts.append("Model confidence is low; treat as a hint, not a verdict.")
    return " ".join(parts)
