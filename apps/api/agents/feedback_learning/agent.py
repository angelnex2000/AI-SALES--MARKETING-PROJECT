"""Feedback Learning Agent — Phase 8 Module 13.

Turns collected feedback into an AI-quality report and a judgement about
whether there is yet enough evidence to retrain anything.

## Every metric is measured or absent

The module brief's dashboard lists "Research Accuracy 92%". Nothing in this
platform can compute that: there is no ground truth for whether a research
report was *correct*, only for whether a human liked it. A number on a screen
labelled "accuracy" that is actually "average star rating from four people" is
worse than a blank, because it will be quoted.

So every metric here carries `available`, `sample_size`, and — when it cannot
be computed — `unavailable_reason` naming what is missing. A metric with no
data reports that it has no data. `MIN_SAMPLE_FOR_DISPLAY` exists for the
adjacent failure: 100% outreach acceptance across two drafts is not 100%
acceptance, and a dashboard that shows it will be believed.

## What each metric actually rests on

  * **outreach_acceptance** — approved / (approved + rejected). Real, from the
    Gate 2 state machine.
  * **human_edit_rate** — mean word-level distance between the AI draft and
    what the human approved, over drafts that still have their original.
  * **reply_intent_accuracy** — measurable only over classifications a human
    explicitly corrected or confirmed, and that sample is **biased**: people
    correct mistakes far more often than they confirm successes. Reported as a
    *lower bound* with the bias stated, never as plain accuracy.
  * **forecast_error** — stored predictions against actual closed-won revenue
    once a period ends. The one metric with real ground truth, and the reason
    `revenue_forecasts` is append-only.
  * **research / ICP / scoring quality** — human ratings only, labelled as
    satisfaction rather than accuracy.

## Nothing here retrains anything

`retraining_readiness` reports sample counts against thresholds and stops. The
brief agrees ("retraining should happen only after proper evaluation, not
automatically"), and the sharper reason is that this feedback is a **biased
sample of a system humans are already steering** — the same trap that keeps
engagement counts out of `lead_scoring/features.py`. Retraining on it without
a held-out evaluation would teach the model to reproduce the reps' existing
preferences and call the agreement an improvement.
"""

from typing import Any

from agents.base import BaseAgent

MODEL_NAME = "feedback_learning"
MODEL_VERSION = "feedback-learning-rules-v1"

# Below this many observations a rate is an anecdote. Displayed as unavailable
# rather than as a confident percentage over three drafts.
MIN_SAMPLE_FOR_DISPLAY = 10

# Observations needed before retraining a given model is worth evaluating.
# Not a trigger — a readiness report a human acts on.
RETRAIN_THRESHOLDS: dict[str, int] = {
    "outreach": 200,
    "reply_intent": 300,
    "lead_scoring": 500,
    "revenue_forecasting": 12,
}

# An edit rate above this says the prompt, not the model, is the problem:
# humans are systematically rewriting the same thing.
EDIT_RATE_CONCERN = 0.40
# Below this, Gate 2 is rejecting more than it accepts.
ACCEPTANCE_CONCERN = 0.60


def metric(
    value: float | None,
    sample_size: int,
    *,
    unit: str = "ratio",
    reason: str | None = None,
    minimum: int = MIN_SAMPLE_FOR_DISPLAY,
) -> dict[str, Any]:
    """One dashboard figure, or an honest explanation of its absence."""

    if reason is not None:
        return {"available": False, "value": None, "sample_size": sample_size, "unit": unit,
                "unavailable_reason": reason}
    if value is None or sample_size < minimum:
        return {
            "available": False,
            "value": None,
            "sample_size": sample_size,
            "unit": unit,
            "unavailable_reason": (
                f"only {sample_size} observation(s); at least {minimum} needed before a rate "
                "means anything"
            ),
        }
    return {"available": True, "value": round(value, 4), "sample_size": sample_size, "unit": unit}


class FeedbackLearningAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """`input_data` is assembled by `feedback_service` — the agent never
        queries the database, so it stays runnable from a mock payload."""

        drafts = input_data.get("drafts") or {}
        edits = input_data.get("edits") or []
        intents = input_data.get("reply_intent") or {}
        forecasts = input_data.get("forecast_errors") or []
        ratings = input_data.get("ratings_by_target") or {}

        metrics = {
            "outreach_acceptance": self._acceptance(drafts),
            "human_edit_rate": self._edit_rate(edits),
            "reply_intent_accuracy": self._intent_accuracy(intents),
            "forecast_error": self._forecast_error(forecasts),
            # Deliberately labelled satisfaction, not accuracy — see module
            # docstring. There is no ground truth for a research report.
            "research_satisfaction": self._satisfaction(ratings.get("research_report")),
            "lead_score_satisfaction": self._satisfaction(ratings.get("lead_score")),
            "icp_satisfaction": self._satisfaction(ratings.get("icp_score")),
        }

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "metrics": metrics,
            "edit_breakdown": self._edit_breakdown(edits),
            "retraining_readiness": self._readiness(input_data.get("training_samples") or {}),
            "observations": self._observations(metrics, edits),
            "explanation": self._explain(metrics),
        }

    # --------------------------------------------------------------- metrics

    def _acceptance(self, drafts: dict[str, Any]) -> dict[str, Any]:
        approved = int(drafts.get("approved") or 0)
        rejected = int(drafts.get("rejected") or 0)
        decided = approved + rejected
        # Pending drafts are excluded: an undecided draft is not a rejection,
        # and counting it as one would make a busy week look like a quality
        # collapse.
        return metric(approved / decided if decided else None, decided)

    def _edit_rate(self, edits: list[dict[str, Any]]) -> dict[str, Any]:
        if not edits:
            return metric(
                None,
                0,
                reason=(
                    "no approved draft has both an AI original and a human revision stored yet — "
                    "edit distance is only measurable once a draft has been edited"
                ),
            )
        values = [float(e["edit_distance"]) for e in edits]
        return metric(sum(values) / len(values), len(values))

    def _intent_accuracy(self, intents: dict[str, Any]) -> dict[str, Any]:
        reviewed = int(intents.get("reviewed") or 0)
        correct = int(intents.get("confirmed") or 0)
        if not reviewed:
            return metric(
                None,
                0,
                reason=(
                    "no reply classification has been confirmed or corrected by a human, so "
                    "there is no ground truth to score against"
                ),
            )
        return metric(correct / reviewed, reviewed)

    def _forecast_error(self, errors: list[dict[str, Any]]) -> dict[str, Any]:
        """MAPE of closed periods only.

        A period still in progress has no actual to compare against; scoring it
        would report a large error every time simply because the month is not
        over.
        """

        closed = [float(e["absolute_percentage_error"]) for e in errors if e.get("period_closed")]
        if not closed:
            return metric(
                None,
                0,
                unit="mape",
                reason="no forecast period has closed yet, so no forecast has an actual to score",
            )
        # Three closed months is a thin but genuine measurement, unlike a rate
        # over three drafts — so this metric uses a lower floor.
        return metric(sum(closed) / len(closed), len(closed), unit="mape", minimum=3)

    def _satisfaction(self, ratings: list[int] | None) -> dict[str, Any]:
        values = [int(r) for r in (ratings or []) if r is not None]
        if not values:
            return metric(None, 0, unit="mean_rating_1_5", reason="no human ratings recorded yet")
        return metric(
            sum(values) / len(values), len(values), unit="mean_rating_1_5", minimum=5
        )

    # -------------------------------------------------------------- rollups

    def _edit_breakdown(self, edits: list[dict[str, Any]]) -> dict[str, Any]:
        """Where the edits land, which is what a prompt change acts on.

        An average alone cannot distinguish "every draft needs a small tidy"
        from "most are perfect and a third are binned" — and those call for
        opposite responses.
        """

        if not edits:
            return {"by_verdict": {}, "subject_change_rate": None, "sample_size": 0}
        by_verdict: dict[str, int] = {}
        subject_changes = 0
        for edit in edits:
            by_verdict[edit["verdict"]] = by_verdict.get(edit["verdict"], 0) + 1
            subject_changes += int(bool(edit.get("subject_changed")))
        return {
            "by_verdict": dict(sorted(by_verdict.items(), key=lambda kv: -kv[1])),
            "subject_change_rate": round(subject_changes / len(edits), 4),
            "sample_size": len(edits),
        }

    def _readiness(self, samples: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for model, threshold in RETRAIN_THRESHOLDS.items():
            have = int(samples.get(model) or 0)
            rows.append(
                {
                    "model": model,
                    "samples": have,
                    "threshold": threshold,
                    "ready_to_evaluate": have >= threshold,
                    # Never "retrain now". Feedback is a biased sample of a
                    # system humans already steer; retraining on it without a
                    # held-out evaluation teaches the model to agree with the
                    # reps and calls that an improvement.
                    "next_step": (
                        "enough data to justify a retraining experiment with a held-out evaluation"
                        if have >= threshold
                        else f"collect {threshold - have} more before evaluating"
                    ),
                }
            )
        return rows

    def _observations(
        self, metrics: dict[str, Any], edits: list[dict[str, Any]]
    ) -> list[str]:
        notes: list[str] = []
        acceptance = metrics["outreach_acceptance"]
        if acceptance["available"] and acceptance["value"] < ACCEPTANCE_CONCERN:
            notes.append(
                f"Gate 2 rejects {(1 - acceptance['value']) * 100:.0f}% of AI drafts — the "
                "outreach prompt is producing text reps do not want to send."
            )
        edit_rate = metrics["human_edit_rate"]
        if edit_rate["available"] and edit_rate["value"] > EDIT_RATE_CONCERN:
            notes.append(
                f"Humans rewrite {edit_rate['value'] * 100:.0f}% of the average draft. At this "
                "level the prompt is the problem, not the model."
            )
        subject_rate = self._edit_breakdown(edits).get("subject_change_rate")
        if subject_rate is not None and subject_rate > 0.7 and len(edits) >= MIN_SAMPLE_FOR_DISPLAY:
            notes.append(
                f"{subject_rate * 100:.0f}% of subject lines are rewritten — a subject-specific "
                "prompt fix, invisible in the combined edit rate."
            )
        intent = metrics["reply_intent_accuracy"]
        if intent["available"]:
            notes.append(
                "Reply-intent accuracy is measured only over classifications a human reviewed. "
                "People correct errors more readily than they confirm successes, so treat it as "
                "a lower bound."
            )
        return notes

    def _explain(self, metrics: dict[str, Any]) -> str:
        available = [name for name, m in metrics.items() if m["available"]]
        missing = [name for name, m in metrics.items() if not m["available"]]
        text = (
            f"{len(available)} of {len(metrics)} quality metrics are measurable from the feedback "
            "collected so far."
        )
        if missing:
            text += (
                f" Not yet measurable: {', '.join(missing)} — each reports why rather than "
                "showing a number that has no evidence behind it."
            )
        return text


__all__ = ["MODEL_NAME", "MODEL_VERSION", "FeedbackLearningAgent", "RETRAIN_THRESHOLDS"]
