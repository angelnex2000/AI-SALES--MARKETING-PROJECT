"""Reply Intent Agent — Phase 8 Module 10.

Turns a messy human email reply into a structured label plus the action it
suggests, so a rep sees "Schedule Meeting" instead of an inbox.

MVP is rule-based. `model.py` and `train.py` are reserved for the fine-tuned
classifier that replaces `_match()` later; the contract, preprocessing,
negation handling, confidence maths and the priority table stay, exactly as in
the Research Agent — the pipeline is built first so swapping the estimator
does not re-litigate any of the above.

Three things this agent will not do:

  * **Read the quoted thread.** `preprocess.clean_reply` runs first. Without
    it the agent classifies our own outreach copy back at us (see that module).
  * **Report a keyword match as near-certainty.** The module brief's worked
    example returns `0.97`. Confidence here is capped at `MAX_CONFIDENCE` and
    scaled down when the reply asks for more than one thing, because this
    number is rendered beside a button a rep is invited to press, and the same
    reasoning applies as to research coverage: an uncalibrated number that
    looks authoritative is worse than a modest one.
  * **Take the action.** `suggested_action` is a suggestion. Nothing downstream
    closes a deal, suppresses a contact or books a meeting off this output —
    the orchestrator writes the result and a timeline entry, and a human
    decides. `mark_closed_lost` fired by a regex on someone's phrasing is
    exactly the failure the platform's human gates exist to prevent.
"""

from typing import Any

from agents.base import BaseAgent
from agents.reply_intent.labels import (
    ACTION_FOR_INTENT,
    INTENT_PRIORITY,
    ReplyIntent,
    SuggestedAction,
)
from agents.reply_intent.preprocess import clean_reply
from agents.reply_intent.rules import RULES, IntentRule, find_match, find_suppressed_match

MODEL_NAME = "reply_intent"
MODEL_VERSION = "reply-intent-rules-v1"

# No keyword match justifies more than this. Kept explicit rather than baked
# into each rule so raising it is a visible, single-line decision.
MAX_CONFIDENCE = 0.90

# Applied when the reply matches more than one intent. "Sounds good — what does
# it cost, and can we talk Thursday?" is three intents in one sentence; picking
# one and reporting it at full confidence hides that a choice was made.
AMBIGUITY_PENALTY = 0.75

# `unknown` is a low-information label by construction, and its action is
# manual review. The brief suggests 0.5, which reads as "half sure" of a label
# that asserts nothing.
UNKNOWN_CONFIDENCE = 0.20

# Below this, the suggested action degrades to manual review whatever the
# label. A rep acting on a 0.45 `mark_closed_lost` is how a team learns to
# distrust the feature.
MIN_ACTIONABLE_CONFIDENCE = 0.50

# These resolve the reply on their own and discard every other match.
# An out-of-office notice's other "intents" belong to an autoresponder, not a
# person; an unsubscribe outranks warmth because the cost of getting it wrong
# is one-sided.
PREEMPTIVE = (ReplyIntent.OUT_OF_OFFICE, ReplyIntent.UNSUBSCRIBE)


class ReplyIntentAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        # `reply_text` is the module brief's field name, `body` is the column
        # on our Reply model. Accepting both keeps the agent runnable from a
        # mock payload without the orchestrator reshaping anything.
        raw = input_data.get("reply_text") or input_data.get("body") or ""
        cleaned = clean_reply(str(raw))

        if not cleaned:
            return self._result(
                ReplyIntent.UNKNOWN,
                UNKNOWN_CONFIDENCE,
                matched_phrase=None,
                alternatives=[],
                cleaned=cleaned,
                explanation=(
                    "The reply carried no new text once the quoted thread and "
                    "signature were removed, so there is nothing to classify. "
                    "This is not a low-confidence reading — it is an empty one."
                ),
            )

        matches = [(rule, phrase) for rule in RULES if (phrase := find_match(rule, cleaned))]

        preemptive = next((m for m in matches if m[0].intent in PREEMPTIVE), None)
        if preemptive is not None:
            return self._preemptive_result(preemptive, matches, cleaned)

        if not matches:
            return self._unknown_result(cleaned)

        matches.sort(key=lambda m: INTENT_PRIORITY[m[0].intent])
        winner, phrase = matches[0]
        ambiguous = len(matches) > 1

        confidence = self._confidence(winner.base_confidence, ambiguous=ambiguous)
        alternatives = [
            {
                "intent": rule.intent.value,
                "confidence": self._confidence(rule.base_confidence, ambiguous=True),
                "matched_phrase": text,
                "suggested_action": ACTION_FOR_INTENT[rule.intent].value,
            }
            for rule, text in matches[1:]
        ]
        return self._result(
            winner.intent,
            confidence,
            matched_phrase=phrase,
            alternatives=alternatives,
            cleaned=cleaned,
            explanation=self._explain(winner, phrase, alternatives, ambiguous),
        )

    # ------------------------------------------------------------------ paths

    def _preemptive_result(
        self,
        preemptive: tuple[IntentRule, str],
        matches: list[tuple[IntentRule, str]],
        cleaned: str,
    ) -> dict[str, Any]:
        rule, phrase = preemptive
        others = [m[0].intent.value for m in matches if m[0].intent is not rule.intent]

        if rule.intent is ReplyIntent.OUT_OF_OFFICE:
            explanation = (
                f'Auto-reply detected from "{phrase}". No action is suggested and the '
                "lead is unchanged: nobody read the email, so the outreach still needs "
                "a response later."
            )
            if others:
                # These come from "for urgent matters call ..." and similar
                # boilerplate — reporting them as alternatives would put a
                # Schedule Meeting button on an absence notice.
                explanation += (
                    f" Wording matching {', '.join(sorted(set(others)))} was ignored: "
                    "in an absence notice it belongs to the autoresponder, not the "
                    "recipient."
                )
        else:
            explanation = (
                f'Opt-out request detected from "{phrase}". This overrides every other '
                "reading of the reply — continuing to email someone who asked us to "
                "stop is a compliance matter, whereas suppressing one lead in error is "
                "not."
            )
            if others:
                explanation += f" Also present but overridden: {', '.join(sorted(set(others)))}."

        return self._result(
            rule.intent,
            # Never scaled down for ambiguity: the whole point of pre-emption is
            # that the other matches are not competing readings.
            min(rule.base_confidence, MAX_CONFIDENCE),
            matched_phrase=phrase,
            alternatives=[],
            cleaned=cleaned,
            explanation=explanation,
        )

    def _unknown_result(self, cleaned: str) -> dict[str, Any]:
        suppressed = {
            rule.intent.value: phrase
            for rule in RULES
            if (phrase := find_suppressed_match(rule, cleaned))
        }
        if suppressed:
            named = ", ".join(f'{intent} ("{phrase}")' for intent, phrase in sorted(suppressed.items()))
            explanation = (
                f"No intent matched. Wording for {named} appears but sits in a negated "
                "clause, so it was not read as a request — a reply that says it does "
                "not want a demo is not a demo request."
            )
        else:
            explanation = (
                "No intent rule matched the reply text. Routed for manual review "
                "rather than guessed at."
            )
        return self._result(
            ReplyIntent.UNKNOWN,
            UNKNOWN_CONFIDENCE,
            matched_phrase=None,
            alternatives=[],
            cleaned=cleaned,
            explanation=explanation,
        )

    # ----------------------------------------------------------------- pieces

    def _confidence(self, base: float, *, ambiguous: bool) -> float:
        value = min(base, MAX_CONFIDENCE)
        if ambiguous:
            value *= AMBIGUITY_PENALTY
        return round(value, 2)

    def _action(self, intent: ReplyIntent, confidence: float) -> SuggestedAction:
        if intent is ReplyIntent.UNSUBSCRIBE:
            # Deliberately exempt. Downgrading an opt-out to "review this later"
            # is the one degradation with a legal cost attached.
            return ACTION_FOR_INTENT[intent]
        if confidence < MIN_ACTIONABLE_CONFIDENCE:
            return SuggestedAction.MANUAL_REVIEW
        return ACTION_FOR_INTENT[intent]

    def _explain(
        self,
        winner: IntentRule,
        phrase: str,
        alternatives: list[dict[str, Any]],
        ambiguous: bool,
    ) -> str:
        parts = [f'Classified as {winner.intent.value} from "{phrase}" in the reply text.']
        if ambiguous:
            others = ", ".join(f'{a["intent"]} ("{a["matched_phrase"]}")' for a in alternatives)
            parts.append(
                f"The reply also matched {others}; {winner.intent.value} was chosen by "
                "priority and confidence was reduced because more than one reading fits."
            )
        return " ".join(parts)

    def _result(
        self,
        intent: ReplyIntent,
        confidence: float,
        *,
        matched_phrase: str | None,
        alternatives: list[dict[str, Any]],
        cleaned: str,
        explanation: str,
    ) -> dict[str, Any]:
        action = self._action(intent, confidence)
        if action is SuggestedAction.MANUAL_REVIEW and intent is not ReplyIntent.UNKNOWN:
            explanation += (
                f" Confidence {confidence} is below the {MIN_ACTIONABLE_CONFIDENCE} "
                "threshold for suggesting an action, so this is routed for manual review."
            )
        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "intent": intent.value,
            "confidence": confidence,
            "suggested_action": action.value,
            "matched_phrase": matched_phrase,
            "alternatives": alternatives,
            "explanation": explanation,
            # Logged to AIInteractionLog so a wrong call can be traced to the
            # text the agent actually saw rather than the raw email.
            "cleaned_text": cleaned,
        }
