"""Campaign selection thresholds and strategy playbook.

Two things live here, both deliberately data rather than code so a marketing
lead can review them without reading Python.

**Selection thresholds belong to the tenant.** The obvious version hardcodes
"lead score > 85 AND ICP > 90 AND signals >= 2". For a tenant with 5,000 leads
that yields a tight, useful list; for one with 60 it yields **zero**, and the
Campaign Studio shows an empty audience with no explanation. Defaults are a
starting point, overridable per request, and the selector reports which
criterion did the eliminating.

**Strategy is a lookup, not an LLM call.** Choosing a consultative tone for
healthcare and a demo CTA for a demo goal is a business rule; routing it
through a language model adds latency, cost and variance to a decision that
has one right answer.
"""

from dataclasses import dataclass
from typing import Any

DEFAULT_CRITERIA: dict[str, Any] = {
    "min_lead_score": 60,
    "min_icp_score": 60,
    "min_buying_signals": 0,
    # Whether a lead that has never been through the intelligence pipeline may
    # be included. Default True: "not yet scored" is not "scored badly", and a
    # new workspace has no scores at all — excluding them silently would make
    # every first campaign empty.
    "include_unscored": True,
    "max_audience": 500,
}


@dataclass(frozen=True)
class CampaignStrategy:
    email_style: str
    cta: str
    sequence_length: int
    case_study_query: str
    """What to ask RAG for. The agent never names a case study itself — one
    must come back from the tenant's own documents or none is used."""
    rationale: str


# Goal → call to action and cadence.
GOAL_PLAYBOOK: dict[str, tuple[str, int]] = {
    "book_demos": ("Schedule a demo", 4),
    "drive_signups": ("Start a free trial", 3),
    "re_engage": ("Reconnect briefly", 2),
    "upsell": ("Review your current usage", 3),
}

# Industry → tone. Regulated industries expect a consultative, evidence-led
# message; a high-energy growth pitch reads as unserious to a hospital
# procurement lead.
INDUSTRY_TONE: dict[str, str] = {
    "healthcare": "Consultative",
    "financial services": "Consultative",
    "government & public sector": "Formal",
    "education": "Consultative",
    "software & saas": "Direct",
    "retail & e-commerce": "Direct",
    "manufacturing": "Practical",
    "logistics & transportation": "Practical",
}

DEFAULT_TONE = "Professional"
DEFAULT_CTA = ("Book a conversation", 3)


def resolve_criteria(overrides: dict[str, Any] | None) -> dict[str, Any]:
    criteria = {**DEFAULT_CRITERIA, **(overrides or {})}
    criteria["max_audience"] = max(1, min(int(criteria["max_audience"]), 5000))
    return criteria


def build_strategy(*, goal: str | None, industry: str | None) -> CampaignStrategy:
    cta, sequence = GOAL_PLAYBOOK.get((goal or "").lower(), DEFAULT_CTA)
    tone = INDUSTRY_TONE.get((industry or "").lower(), DEFAULT_TONE)

    sector = industry or "this sector"
    reasons = [f"{tone} tone for {sector}"]
    if goal:
        reasons.append(f"CTA '{cta}' matches the goal '{goal}'")
    reasons.append(f"{sequence}-step sequence")

    return CampaignStrategy(
        email_style=tone,
        cta=cta,
        sequence_length=sequence,
        case_study_query=f"{sector} customer outcome case study",
        rationale="; ".join(reasons) + ".",
    )
