"""Buying-signal rule definitions.

A buying signal is a **timing** claim: not "is this a good fit" (that's ICP
matching) but "is something happening at this company right now that creates
a need". That makes provenance decisive — a signal only means something if it
came from something that actually happened.

`SignalType` is a Python enum so rules stay consistent, but
`BuyingSignal.signal_type` stays a plain `String` column. Unlike `Role` or
`DealStage` — closed sets the product is built around — signal types grow
every time someone adds a rule, and a DB enum would mean a migration per
addition for no queryable benefit.
"""

import re
from dataclasses import dataclass
from enum import Enum


class SignalType(str, Enum):
    FUNDING = "funding"
    HIRING = "hiring"
    EXPANSION = "expansion"
    PRODUCT_LAUNCH = "product_launch"
    DIGITAL_TRANSFORMATION = "digital_transformation"
    LEADERSHIP_CHANGE = "leadership_change"
    SUPPORT_LOAD = "support_load"
    PARTNERSHIP = "partnership"


@dataclass(frozen=True)
class SignalRule:
    signal_type: SignalType
    patterns: tuple[str, ...]
    description: str
    base_confidence: float
    """How much this pattern tells us **when matched against real evidence**.
    The agent scales it down by the research report's own coverage — a signal
    cannot be more certain than the report it was read from."""


# Patterns match on word boundaries, not substrings. Naive `in` matching fires
# "funding" on "refunding", "support" on "unsupported", and "hiring" on
# "hiring freeze" — the opposite signal. Each false positive pushes a lead up
# a rep's queue for no reason.
RULES: tuple[SignalRule, ...] = (
    SignalRule(
        SignalType.FUNDING,
        (r"funding", r"raised", r"series [a-e]\b", r"investment round", r"venture round"),
        "Recent funding suggests budget is available.",
        0.85,
    ),
    SignalRule(
        SignalType.HIRING,
        (r"hiring", r"recruiting", r"new roles?", r"headcount growth", r"job openings?"),
        "Hiring activity suggests the team is scaling.",
        0.75,
    ),
    SignalRule(
        SignalType.EXPANSION,
        (r"expansion", r"expanding", r"new branch(es)?", r"new (office|location|market)s?"),
        "Expansion creates new operational needs.",
        0.85,
    ),
    SignalRule(
        SignalType.PRODUCT_LAUNCH,
        (r"launch(ed|ing)?", r"new product", r"rolled out", r"unveiled"),
        "A product launch often drives new go-to-market work.",
        0.70,
    ),
    SignalRule(
        SignalType.DIGITAL_TRANSFORMATION,
        (r"digital transformation", r"telemedicine", r"automation", r"cloud migration", r"ai\b"),
        "Digital initiatives suggest appetite for automation tooling.",
        0.80,
    ),
    SignalRule(
        SignalType.LEADERSHIP_CHANGE,
        (r"new (ceo|cto|cio|coo|vp|head of)", r"appointed", r"joins as"),
        "A new decision-maker often reopens tooling decisions.",
        0.70,
    ),
    SignalRule(
        SignalType.SUPPORT_LOAD,
        (r"support (volume|workload|backlog)", r"inquiry volume", r"ticket backlog", r"wait times?"),
        "Rising support load suggests a need for deflection or automation.",
        0.75,
    ),
    SignalRule(
        SignalType.PARTNERSHIP,
        (r"partnership", r"partnered", r"acquisition", r"acquired", r"merger"),
        "Partnerships and acquisitions trigger systems consolidation.",
        0.70,
    ),
)

# Phrases that invert a match. "hiring freeze" contains "hiring" but means the
# opposite; treating it as growth puts a company that just stopped spending at
# the top of a rep's list.
NEGATIONS: tuple[str, ...] = (
    r"hiring freeze",
    r"layoffs?",
    r"downsizing",
    r"cost[- ]cutting",
    r"scaled back",
    r"no plans to",
    r"postponed",
)

_NEGATION_RE = re.compile("|".join(NEGATIONS), re.IGNORECASE)


def is_negated(text: str) -> bool:
    """True if the text carries a phrase that reverses the signal's meaning."""

    return bool(_NEGATION_RE.search(text))


def matches(rule: SignalRule, text: str) -> str | None:
    """Return the matched phrase, or None. Word-boundary anchored."""

    for pattern in rule.patterns:
        found = re.search(rf"\b(?:{pattern})", text, re.IGNORECASE)
        if found:
            return found.group(0)
    return None
