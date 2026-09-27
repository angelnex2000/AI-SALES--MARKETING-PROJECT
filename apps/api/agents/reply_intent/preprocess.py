"""Reduce a raw inbound email to the words the customer actually typed.

This module is the difference between a working classifier and one that reads
its own outbox. An email reply is not a sentence — it is the customer's few
words followed by a verbatim copy of the message we sent them:

    No thanks.

    On Tue, 4 Aug 2026 at 09:12, Priya <priya@acme.com> wrote:
    > Hi Ravi, would you be open to a quick demo next week? Happy to share
    > pricing too — just let me know a time that works.

Classify the whole body and every positive rule fires on **our own pitch**:
"demo", "pricing", "let me know a time". A flat refusal becomes
`meeting_request`, confidence 0.9, suggested action `schedule_meeting`. No
amount of care in the rule table fixes that, because the rules are being
shown the wrong text. So the quoted thread is removed before anything else
happens.

Everything here is conservative by design. Over-stripping deletes the one
sentence that carries the intent and produces a confident `unknown`, so each
cut is anchored to a marker that email clients actually emit rather than to a
guess about where the "real" text ends.

Assumes top-posting (reply above the quote), which is what Gmail, Outlook,
Apple Mail and every mobile client do by default. A bottom-posted reply loses
its text here and falls through to `unknown` → manual review, which is the
safe direction to fail.
"""

import re

# The first line of the quoted original. Each of these is emitted verbatim by
# a mainstream client; everything from the match onward is our own email.
QUOTE_MARKERS: tuple[str, ...] = (
    r"^\s*On .{1,200}\bwrote:\s*$",                    # Gmail, Apple Mail
    r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$",       # Outlook (plain text)
    r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$",
    r"^\s*_{5,}\s*$",                                   # Outlook divider rule
    r"^\s*From:\s*.+$",                                 # Outlook header block
    r"^\s*Sent:\s*.+$",
    r"^\s*\*?From:\*?\s*.+$",
    r"^\s*El .{1,200}\bescribió:\s*$",                  # es
    r"^\s*Le .{1,200}\ba écrit\s*:\s*$",                # fr
    r"^\s*Am .{1,200}\bschrieb\b.*:\s*$",               # de
)

# Signature blocks. Only the two forms that are unambiguous: the RFC 3676
# `-- ` delimiter, and the mobile-client footer. Heuristics like "cut at
# 'Best regards'" are not used — plenty of real replies say "Best regards"
# and then keep going with the actual answer.
SIGNATURE_MARKERS: tuple[str, ...] = (
    r"^--\s*$",
    r"^\s*Sent from my \w+",
    r"^\s*Get Outlook for \w+",
    r"^\s*Sent via \w+",
)

# Corporate confidentiality footers. These matter more than they look: the
# standard wording is "if you have received this in error please call the
# sender immediately and delete" — which fires the meeting-request rules on
# boilerplate that no human wrote for us.
DISCLAIMER_MARKERS: tuple[str, ...] = (
    r"^\s*This (e-?mail|message)( and any attachments)? (is|are|may be) "
    r"(confidential|privileged|intended)",
    r"^\s*The information (contained )?in this (e-?mail|message)",
    r"^\s*CONFIDENTIALITY NOTICE",
    r"^\s*DISCLAIMER\s*:?\s*$",
    r"^\s*P\.?\s?lease consider the environment before printing",
)

_FLAGS = re.IGNORECASE | re.MULTILINE
_QUOTE_RE = re.compile("|".join(QUOTE_MARKERS), _FLAGS)
_SIGNATURE_RE = re.compile("|".join(SIGNATURE_MARKERS), _FLAGS)
_DISCLAIMER_RE = re.compile("|".join(DISCLAIMER_MARKERS), _FLAGS)
_QUOTED_LINE_RE = re.compile(r"^\s*>.*$", re.MULTILINE)


def _truncate_at(text: str, pattern: re.Pattern[str]) -> str:
    found = pattern.search(text)
    return text[: found.start()] if found else text


def clean_reply(body: str) -> str:
    """Return only the newly written portion of an inbound email.

    An empty result is meaningful and must not be treated as a failure: it
    means the message carried no new text (a bare quote, or an empty body from
    the provider). The agent reports that case distinctly, because "they wrote
    nothing we can read" and "they wrote something we couldn't interpret" call
    for different handling by the rep.
    """

    if not body:
        return ""

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = _truncate_at(text, _QUOTE_RE)
    # Belt and braces: some clients quote with `>` and no header line at all,
    # and a forwarded chain can nest quote markers below the first one.
    text = _QUOTED_LINE_RE.sub("", text)
    text = _truncate_at(text, _SIGNATURE_RE)
    text = _truncate_at(text, _DISCLAIMER_RE)

    # Collapse the whitespace the cuts leave behind so downstream patterns can
    # match across what were line breaks ("can we schedule\na demo").
    return re.sub(r"\s+", " ", text).strip()
