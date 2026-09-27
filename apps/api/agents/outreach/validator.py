"""Validates a generated draft before it is offered for approval.

## What this can and cannot do

It catches **structural** failures: an uncited figure, a citation to a source
that was never retrieved, a leftover `{{placeholder}}`, a missing call to
action, an email that is three times too long.

It does **not** verify that the email is true. Nothing automated can: a
sentence can cite [S1] correctly and still misrepresent what [S1] says. So
validation is a filter that removes obvious defects before a human looks, not
a substitute for the human. **Gate 2 remains the control** — that is why
`SEVERITY_BLOCK` findings mark the draft for attention rather than
auto-approving anything, and why nothing here can move a draft past
`pending_approval`.

The most valuable check is the cheapest: **specific numbers with no
citation**. That is the literal shape of the failure this whole feature exists
to prevent — "we reduced hospital support cost by 80%" when nobody ever
measured it.
"""

import re
from typing import Any

from agents.rag.prompt_builder import verify_citations

SEVERITY_BLOCK = "block"
"""Do not present this draft as ready. A reviewer may still fix and approve
it, but the UI should lead with the problem."""
SEVERITY_WARN = "warn"

MIN_BODY_CHARS = 200
MAX_BODY_CHARS = 2000
"""A cold outreach email past ~2000 characters does not get read. Longer than
this is a generation failure, not a style preference."""
MAX_SUBJECT_CHARS = 120

# Text a template or a model left behind. Shipping "Hi {{first_name}}" to a
# prospect is worse than any hallucination for how it reads.
_PLACEHOLDER = re.compile(r"\{\{.*?\}\}|\[\[.*?\]\]|<[A-Z_]{3,}>|\bTODO\b|\bXXX\b")

# Claims of certainty a grounded email should not make on our behalf.
_OVERCLAIM = re.compile(
    r"\b(guarantee[ds]?|guaranteed|100% (?:success|uptime|satisfaction)|"
    r"best in the world|no risk|risk[- ]free|instantly)\b",
    re.IGNORECASE,
)

_CTA_HINTS = (
    "?",
    "book",
    "schedule",
    "demo",
    "call",
    "meeting",
    "chat",
    "connect",
    "reply",
    "available",
)


def _finding(code: str, message: str, severity: str = SEVERITY_WARN) -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def validate_draft(
    *,
    subject: str,
    body: str,
    citation_map: dict[str, str],
    require_cta: bool = True,
) -> dict[str, Any]:
    """Return `{valid, findings, citations}`.

    `valid` is False only for blocking findings; warnings still surface to the
    reviewer but do not imply the draft is unusable.
    """

    findings: list[dict[str, str]] = []
    subject = (subject or "").strip()
    body = (body or "").strip()

    if not subject:
        findings.append(_finding("EMPTY_SUBJECT", "Subject is empty.", SEVERITY_BLOCK))
    elif len(subject) > MAX_SUBJECT_CHARS:
        findings.append(
            _finding("SUBJECT_TOO_LONG", f"Subject exceeds {MAX_SUBJECT_CHARS} characters.")
        )

    if not body:
        findings.append(_finding("EMPTY_BODY", "Body is empty.", SEVERITY_BLOCK))
    else:
        if len(body) < MIN_BODY_CHARS:
            findings.append(_finding("BODY_TOO_SHORT", "Body is too short to be useful."))
        if len(body) > MAX_BODY_CHARS:
            findings.append(
                _finding("BODY_TOO_LONG", f"Body exceeds {MAX_BODY_CHARS} characters.")
            )

    combined = f"{subject}\n{body}"

    leftovers = _PLACEHOLDER.findall(combined)
    if leftovers:
        findings.append(
            _finding(
                "UNFILLED_PLACEHOLDER",
                f"Unfilled placeholder(s): {', '.join(sorted(set(leftovers))[:3])}.",
                SEVERITY_BLOCK,
            )
        )

    overclaims = _OVERCLAIM.findall(body)
    if overclaims:
        findings.append(
            _finding(
                "OVERCLAIM",
                f"Language we cannot stand behind: {', '.join(sorted(set(overclaims))[:3])}.",
                SEVERITY_BLOCK,
            )
        )

    citations = verify_citations(body, citation_map)
    if citations["unknown_markers"]:
        findings.append(
            _finding(
                "UNKNOWN_CITATION",
                f"Cites {', '.join(citations['unknown_markers'])}, which was never retrieved.",
                SEVERITY_BLOCK,
            )
        )
    if citations["uncited_numeric_claim"]:
        # The shape of an invented metric, and the reason this module exists.
        findings.append(
            _finding(
                "UNCITED_FIGURE",
                "Contains specific figures with no cited source.",
                SEVERITY_BLOCK,
            )
        )

    if require_cta and body and not any(hint in body.lower() for hint in _CTA_HINTS):
        findings.append(_finding("NO_CTA", "No call to action or question."))

    blocking = [f for f in findings if f["severity"] == SEVERITY_BLOCK]
    return {
        "valid": not blocking,
        "findings": findings,
        "blocking_count": len(blocking),
        "citations": citations,
    }


def strip_citation_markers(text: str) -> str:
    """Remove `[S1]` markers for the customer-facing copy.

    The markers exist so the reviewer and the validator can trace claims; a
    prospect should not receive them. Called only after validation, so the
    stored `body` is what would actually be sent while `citations` records
    what backed it.
    """

    return re.sub(r"\s*\[S\d+\]", "", text or "").strip()
