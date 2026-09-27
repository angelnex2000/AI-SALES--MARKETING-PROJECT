"""ICP definition and per-attribute scoring.

**The ICP belongs to the tenant, not to us.** This is multi-tenant SaaS: a
German logistics vendor and an Indian health-tech startup have nothing in
common in who they want to sell to. Hardcoding one target profile into shared
agent code would tell every customer that their best leads are whichever ones
match someone else's business — confidently, with a number attached.

So the profile is read from `Company.icp_config` and `DEFAULT_ICP` is only a
starting point for a workspace nobody has configured yet.

A second rule runs through the scoring below: **"we don't know" is not the
same as "bad fit"**. A lead with no industry recorded scores `UNKNOWN_SCORE`
(neutral) and is counted as a gap in `confidence`, rather than being scored
like a known mismatch. Otherwise reps quietly deprioritise every lead nobody
has finished researching — the opposite of what the tool is for.
"""

from typing import Any

# Neutral, not bad. Sits between MISMATCH and a partial match so an
# unresearched lead is never ranked below a known-wrong one.
UNKNOWN_SCORE = 50.0
MISMATCH_SCORE = 20.0
PARTIAL_SCORE = 65.0
STRONG_SCORE = 100.0

DEFAULT_ICP: dict[str, Any] = {
    "target_industries": ["healthcare", "banking", "education", "insurance", "saas"],
    # Empty means "region is not a criterion" — scored neutral rather than
    # penalising every lead outside an arbitrary home market.
    "target_countries": [],
    "min_employees": 100,
    "ideal_employees": 500,
    "weights": {
        "industry": 0.30,
        "company_size": 0.30,
        "region": 0.20,
        "need": 0.20,
    },
}


def resolve_profile(config: dict[str, Any] | None) -> dict[str, Any]:
    """Merge a tenant's stored config over the defaults.

    Shallow-merges so a tenant that only overrode `target_industries` still
    gets default weights, and normalises weights to sum to 1.0 — otherwise a
    tenant who set them to 0.5/0.5/0.5/0.5 would produce overall scores above
    100 and break every comparison built on them.
    """

    profile = {**DEFAULT_ICP, **(config or {})}
    weights = {**DEFAULT_ICP["weights"], **(profile.get("weights") or {})}

    total = sum(weights.values())
    if total <= 0:
        weights = dict(DEFAULT_ICP["weights"])
    else:
        weights = {k: v / total for k, v in weights.items()}

    profile["weights"] = weights
    profile["target_industries"] = [str(i).lower() for i in profile.get("target_industries") or []]
    profile["target_countries"] = [str(c).lower() for c in profile.get("target_countries") or []]
    return profile


def score_industry(industry: str | None, profile: dict[str, Any]) -> tuple[float, bool]:
    """Return `(score, known)`. `known` feeds confidence, not the score."""

    if not industry:
        return UNKNOWN_SCORE, False
    targets = profile["target_industries"]
    if not targets:
        return UNKNOWN_SCORE, False
    return (STRONG_SCORE if industry.lower() in targets else MISMATCH_SCORE), True


def score_company_size(employees: int | None, profile: dict[str, Any]) -> tuple[float, bool]:
    if employees is None:
        return UNKNOWN_SCORE, False
    if employees >= profile["ideal_employees"]:
        return STRONG_SCORE, True
    if employees >= profile["min_employees"]:
        return PARTIAL_SCORE, True
    return MISMATCH_SCORE, True


def score_region(country: str | None, profile: dict[str, Any]) -> tuple[float, bool]:
    targets = profile["target_countries"]
    if not targets:
        # The tenant sells everywhere, so region carries no information.
        return UNKNOWN_SCORE, False
    if not country:
        return UNKNOWN_SCORE, False
    return (STRONG_SCORE if country.lower() in targets else MISMATCH_SCORE), True


def score_need(signals: list[dict[str, Any]]) -> tuple[float, bool]:
    """Need is scored from **buying signals**, which are evidence-derived
    (see `agents/buying_signals/agent.py`), not from the research report's
    inferred pain points.

    Scoring inferred pain points here would double-count industry: the
    playbook derives "High patient inquiry volume" *from* `industry =
    Healthcare`, so industry would drive both `industry_score` (30%) and
    `pain_point_score` (20%) — half the ICP score from one field, looking like
    two independent confirmations.
    """

    if not signals:
        return UNKNOWN_SCORE, False
    strongest = max(float(s.get("confidence") or 0.0) for s in signals)
    # Two or more independent signals is a stronger case than one.
    breadth_bonus = 10.0 if len({s.get("signal_type") for s in signals}) > 1 else 0.0
    return min(STRONG_SCORE, round(strongest * 100 + breadth_bonus, 1)), True
