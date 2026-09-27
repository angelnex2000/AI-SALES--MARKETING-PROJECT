"""Pattern rules for reply-intent classification.

Same discipline as `agents/buying_signals/signals.py`, for the same reason:
naive substring matching produces confident wrong answers. `"cost" in text`
fires on *costume* and *costly*; `"call" in text` fires on *recall*. Every
pattern here is anchored on a word boundary.

What is different — and harder — than buying signals is **negation**. A buying
signal reads a third-party news item; a reply is a person answering us, and the
most common way to answer is to name the thing you are declining:

    "We're not looking for a demo right now."
    "I don't need pricing, we've already chosen a vendor."

Both contain the keyword for an intent that is the opposite of what was meant,
and both are ordinary sentences a rep receives every week. So a keyword match
is only accepted after `is_negated_at()` checks the clause it sits in.
"""

import re
from dataclasses import dataclass

from agents.reply_intent.labels import ReplyIntent


@dataclass(frozen=True)
class IntentRule:
    intent: ReplyIntent
    patterns: tuple[str, ...]
    base_confidence: float
    """How much a clean match tells us. Capped well below 1.0 in agent.py:
    a keyword hit is not a 97%-certain reading of a human sentence, and this
    number is rendered next to an action a rep is invited to take."""
    negatable: bool = True
    """False where negation is already part of the phrase's meaning.
    "not interested" must not be suppressed for containing "not"."""


RULES: tuple[IntentRule, ...] = (
    IntentRule(
        ReplyIntent.OUT_OF_OFFICE,
        (
            r"out of (the )?office",
            r"auto(matic|mated)?[- ]?(reply|response|responder)",
            r"on (annual|parental|maternity|paternity|sick|medical|study) leave",
            r"on leave (until|till|up to)",
            r"on (vacation|holiday|sabbatical)",
            r"away from (my|the) (desk|office)",
            r"currently (out|unavailable|away)",
            r"(am|i'?m) (currently )?travell?ing",
            r"limited access to (my )?e-?mail",
            r"(will (be )?back|will return|returning) (on|to the office)",
            r"back in the office on",
            r"no longer with (the company|us|\w+ ltd)",
        ),
        0.85,
        negatable=False,
    ),
    IntentRule(
        ReplyIntent.UNSUBSCRIBE,
        (
            r"unsubscrib(e|ed|ing)",
            r"remove me from",
            r"take me off (your|the) (list|mailing|database)",
            r"stop (e-?mailing|contacting|sending|messaging)",
            r"do not (contact|e-?mail|message) me",
            r"don'?t (contact|e-?mail|message) me",
            r"opt[- ]?out",
            r"no longer wish to receive",
            r"delete my (details|data|information)",
        ),
        0.90,
        negatable=False,
    ),
    IntentRule(
        ReplyIntent.NOT_INTERESTED,
        (
            r"not interested",
            r"no interest",
            r"not (a|the right) (good )?fit",
            r"no,? thanks?\b",
            r"no,? thank you",
            r"we'?re (all set|good|sorted)",
            r"already (have|use|using|working with|signed with|chosen|selected|picked|decided|committed)",
            r"(went|going|gone) with (another|a different|someone)",
            r"(chose|chosen|selected|picked) (another|a different)",
            # "we have already chosen a vendor" — the most common way a
            # rejection is written, and the one the keyword list missed.
            r"(chose|chosen|selected|picked|went with) (a |an |the )?"
            r"(other |different )?(vendor|supplier|provider|solution|tool|platform|partner)",
            r"decided (to go with|against|not to)",
            r"we'?ll pass",
            r"(going to|gonna) pass",
            r"not (looking|in the market)",
            r"please stop",
        ),
        0.80,
        negatable=False,
    ),
    IntentRule(
        ReplyIntent.MEETING_REQUEST,
        (
            r"(schedule|book|set ?up|arrange|organi[sz]e) a (call|meeting|demo|chat|time|slot)",
            r"\bdemo\b",
            r"\bmeeting\b",
            r"\bcalls?\b",
            r"calendar",
            r"calendly",
            r"are you (free|available)",
            r"what times? (works?|suits?)",
            r"(does|would) \w+ work for you",
            r"jump on a (call|zoom|meet)",
            r"hop on a (call|zoom|meet)",
            r"(can|could|shall|should|would) we (talk|chat|speak|connect|meet)",
            r"let'?s (talk|chat|connect|meet|discuss)",
            r"(happy|glad|open) to (talk|chat|connect|meet)",
            r"(send|share) (me )?(your|a) (calendar|availability)",
            r"walk (me|us) through",
        ),
        0.80,
    ),
    IntentRule(
        ReplyIntent.PRICING_REQUEST,
        (
            r"pricing",
            r"\bprices?\b",
            r"\bquote\b",
            r"\bcosts?\b",
            r"how much (does|is|would|will)",
            r"\bbudgets?\b",
            r"(rate card|price list|pricing (page|sheet|deck))",
            r"\bproposals?\b",
            r"per (seat|user|month|licen[cs]e)",
            r"payment terms",
        ),
        0.80,
    ),
    IntentRule(
        ReplyIntent.FOLLOW_UP_LATER,
        (
            r"next (month|quarter|year|financial year|fy)",
            r"later (this|next) (year|quarter|month)",
            r"in (a|the|another) (few|couple of) (weeks|months|quarters)",
            r"circle back",
            r"check back",
            r"touch base (later|next|in)",
            r"reach out (again|later|in|next)",
            r"revisit (this|it|in|next)",
            r"not (right now|at this time|at the moment|currently)",
            r"after (the )?(new year|budget|q[1-4]|diwali|christmas|holidays)",
            r"(get|come) back to you (later|next|in)",
            r"ping me (later|next|in)",
            r"keep (me|us) posted",
        ),
        0.70,
        # "not right now" is a deferral written with a negator; suppressing it
        # for containing "not" would delete the rule.
        negatable=False,
    ),
    IntentRule(
        ReplyIntent.INTERESTED,
        (
            r"interested",
            r"sounds (good|great|interesting|useful|promising)",
            r"tell me more",
            r"learn more",
            r"(send|share) (me )?more (info|information|details)",
            r"keen to",
            r"(would|i'?d) like to (know|hear) more",
            r"looks (good|interesting|promising|useful)",
            r"this could (be|work)",
            r"worth (a|exploring|discussing)",
        ),
        # Lowest of the positives on purpose: "sounds interesting" is as often
        # politeness on the way to a no as it is a real signal, and unlike a
        # meeting or pricing ask it commits the sender to nothing.
        0.60,
    ),
)


# Words that flip the clause they appear in. `n'?t` covers don't/won't/can't/
# isn't/doesn't as a suffix, so each contraction does not need its own entry.
NEGATORS: tuple[str, ...] = (
    r"\bnot\b",
    r"n'?t\b",
    r"\bno\b",
    r"\bnever\b",
    r"\bwithout\b",
    r"\bunable\b",
    r"\bstop\b",
    r"\bcancel(l?ed|l?ing)?\b",
    r"\bdecline[ds]?\b",
    r"\bskip\b",
)

# How far back to look for a negator. Long enough to cover "we are not really
# looking for a " (~30 chars) before a keyword, short enough that a negator in
# an unrelated earlier phrase does not reach it.
NEGATION_WINDOW = 40

# A negator stops applying at a clause boundary. Without this,
# "I'm not sure I follow, but yes — let's book a demo" reads as negated,
# because "not" sits 40 characters before "demo" with a full clause in between.
_CLAUSE_BOUNDARY_RE = re.compile(r"[.;!?,]|\b(?:but|however|though|although|still|anyway)\b", re.IGNORECASE)
_NEGATOR_RE = re.compile("|".join(NEGATORS), re.IGNORECASE)


def is_negated_at(text: str, start: int) -> bool:
    """True if the match beginning at `start` sits in a negated clause.

    Scans backwards a bounded window, then discards anything before the last
    clause boundary — a negator only reaches the keyword if nothing separates
    them.
    """

    window = text[max(0, start - NEGATION_WINDOW) : start]
    boundaries = list(_CLAUSE_BOUNDARY_RE.finditer(window))
    if boundaries:
        window = window[boundaries[-1].end() :]
    return bool(_NEGATOR_RE.search(window))


def find_match(rule: IntentRule, text: str) -> str | None:
    """Return the phrase that matched this rule, or None.

    Word-boundary anchored, and — for negatable rules — skipping matches whose
    clause reverses them. A rule with several patterns keeps looking after a
    negated hit, so "we don't need a demo, but can you send your calendar"
    still resolves to a meeting request.
    """

    for pattern in rule.patterns:
        for found in re.finditer(rf"\b(?:{pattern})", text, re.IGNORECASE):
            if rule.negatable and is_negated_at(text, found.start()):
                continue
            return found.group(0)
    return None


def find_suppressed_match(rule: IntentRule, text: str) -> str | None:
    """The phrase this rule *would* have matched had negation been ignored.

    Used only to explain an `unknown` result. "We don't need a demo" is not a
    classifier failure — it is a rejection the rules correctly refused to read
    as a booking — and a rep looking at a blank result deserves to be told that
    rather than concluding the agent is broken.
    """

    if not rule.negatable:
        return None
    for pattern in rule.patterns:
        found = re.search(rf"\b(?:{pattern})", text, re.IGNORECASE)
        if found:
            return found.group(0)
    return None
