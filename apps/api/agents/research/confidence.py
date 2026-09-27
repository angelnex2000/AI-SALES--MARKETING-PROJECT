"""Confidence scoring for the Research Agent.

This is **evidence coverage, not truth probability**. It answers "how much did
we actually find?", not "how likely is this correct?" — and it is computed
from observable signals, never asked of the language model. A model's
self-reported confidence is an uncalibrated guess that looks authoritative,
and this number is not cosmetic: it is stored on every AI output
(`AIOutputMixin.confidence`) and Lead Scoring consumes it downstream, so a
fabricated 0.91 would propagate into a figure a Sales Manager prioritises
work by.

Naming it honestly matters. When the Lead Details page shows "confidence
0.4", the right reading is "we found little about this company", not "we are
40% sure this is true".
"""

from agents.research.schemas import ResearchInput

# Weights sum to 1.0. Ordered by how much each signal actually tells us: an
# identified website and real news are worth more than a country field.
WEIGHTS = {
    "website_known": 0.25,
    "industry_known": 0.20,
    "recent_news_found": 0.25,
    "size_known": 0.15,
    "crm_notes_present": 0.15,
}

# Below this, the report is too thin to act on. Callers should surface it as
# "insufficient data" rather than showing a confident-looking report.
LOW_CONFIDENCE_THRESHOLD = 0.35


def score(*, payload: ResearchInput, news_count: int) -> tuple[float, list[str]]:
    """Return `(confidence, reasons)`.

    `news_count` must be **externally sourced items only**. Passing the full
    evidence list double-counts: CRM notes already score through
    `crm_notes_present`, and the lead-origin line is a CRM fact rather than
    news, so a lead with notes and a source collected 0.40 of coverage for one
    thing we knew.

    `reasons` is returned alongside so the explanation stored on the report
    states what was and wasn't available, instead of leaving a bare number to
    be interpreted.
    """

    signals = {
        "website_known": bool(payload.website),
        "industry_known": bool(payload.industry),
        "recent_news_found": news_count > 0,
        "size_known": payload.employees is not None,
        "crm_notes_present": bool(payload.crm_notes),
    }

    confidence = sum(WEIGHTS[name] for name, present in signals.items() if present)
    missing = [name.replace("_", " ") for name, present in signals.items() if not present]

    reasons = []
    present = [name.replace("_", " ") for name, ok in signals.items() if ok]
    if present:
        reasons.append("based on: " + ", ".join(present))
    if missing:
        reasons.append("missing: " + ", ".join(missing))

    # Guard against float drift making a full-coverage report score 0.9999.
    return round(min(confidence, 1.0), 2), reasons


def is_actionable(confidence: float) -> bool:
    return confidence >= LOW_CONFIDENCE_THRESHOLD
