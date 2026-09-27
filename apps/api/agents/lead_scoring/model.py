"""Lead Scoring Agent — inference.

Answers the question a rep asks every morning: *of these 10,000 leads, which
do I call first?* That is a **ranking** problem, not a yes/no classification,
which is why the model is judged on lift rather than accuracy.

## How the score is built

    historical fit  (trained model, firmographics)  -> P(convert)
    tenant fit      (ICP matching)                  -> bounded adjustment
    timing          (buying signals)                -> bounded adjustment
                                                    = 0-100 score

The three stay separate and are reported individually in `components` rather
than fused into one opaque number. They answer genuinely different questions —
"do companies like this convert", "does this tenant want them", "is something
happening now" — so a rep who disagrees with a score can see which of the
three drove it. Module 6 (explainability) builds directly on this.

## Honest reporting of model quality

The trained model reaches **ROC-AUC ~0.62** with **1.48x lift in the top
decile** on a temporal holdout: top-decile leads convert at 45% against a
30.5% base rate. Real and useful, but not the 0.94 "probability" a naive
design implies. `confidence` reports the model's *measured discrimination*
rather than a number invented per prediction, so nothing downstream can
present a weak model as a certain one.
"""

import json
import logging
from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from agents.lead_scoring.features import build_features, describe_features

logger = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).parent / "artifacts"
MODEL_PATH = ARTIFACT_DIR / "lead_scoring.joblib"
METRICS_PATH = ARTIFACT_DIR / "metrics.json"

MODEL_NAME = "lead_scoring"
TRAINED_VERSION = "lead-scoring-gbdt-v1"
HEURISTIC_VERSION = "lead-scoring-heuristic-v1"

# How far ICP fit and buying signals may move the model's baseline. Bounded on
# purpose: uncapped, a lead with a few signals would saturate at 100 whether or
# not the company resembles anyone we have ever sold to.
ICP_WEIGHT = 0.25
SIGNAL_WEIGHT = 0.15

_model_cache: dict[str, Any] = {}


def _load() -> tuple[Any | None, dict[str, Any]]:
    """Load the trained artifact once per process. A missing artifact is not
    an error — a fresh checkout has none and must still score leads."""

    if "loaded" not in _model_cache:
        model: Any | None = None
        metrics: dict[str, Any] = {}
        if MODEL_PATH.exists():
            try:
                import joblib

                model = joblib.load(MODEL_PATH)["model"]
                if METRICS_PATH.exists():
                    metrics = json.loads(METRICS_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                # A corrupt artifact must not take down the intelligence
                # pipeline; fall back to the heuristic and say so in the output.
                logger.error("could not load lead scoring model", exc_info=exc)
                model = None
        _model_cache["loaded"] = (model, metrics)
    return _model_cache["loaded"]


def reset_cache() -> None:
    """For tests that swap artifacts in and out."""

    _model_cache.clear()


class LeadScoringAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        lead = input_data.get("lead") or {}
        icp = input_data.get("icp") or {}
        signals = (input_data.get("signals") or {}).get("signals") or []

        model, metrics = _load()
        features = build_features(lead)

        if model is not None:
            probability = float(model.predict_proba([features])[0][1])
            version = TRAINED_VERSION
            # Discrimination measured on a temporal holdout, not a per-lead
            # guess. AUC 0.5 is random, so (auc - 0.5) * 2 maps onto [0, 1].
            auc = float(metrics.get("roc_auc") or 0.5)
            confidence = round(max(0.0, (auc - 0.5) * 2), 2)
        else:
            probability = self._heuristic(lead)
            version = HEURISTIC_VERSION
            # Untrained: usable for ordering, but nothing about it is measured.
            confidence = 0.1

        icp_fit = float(icp.get("overall_score") or 50.0) / 100.0
        signal_strength = max((float(s.get("confidence") or 0.0) for s in signals), default=0.0)

        base = probability * 100
        icp_adjustment = (icp_fit - 0.5) * ICP_WEIGHT * 100
        signal_adjustment = signal_strength * SIGNAL_WEIGHT * 100
        score = max(0, min(100, round(base + icp_adjustment + signal_adjustment)))

        return {
            "model_name": MODEL_NAME,
            "model_version": version,
            "score": score,
            "probability": round(probability, 4),
            "confidence": confidence,
            "components": {
                "historical_fit": round(base, 1),
                "icp_adjustment": round(icp_adjustment, 1),
                "signal_adjustment": round(signal_adjustment, 1),
            },
            "active_features": describe_features(features),
            "explanation": self._explanation(
                score=score,
                probability=probability,
                icp_adjustment=icp_adjustment,
                signal_adjustment=signal_adjustment,
                trained=model is not None,
                metrics=metrics,
            ),
        }

    def _heuristic(self, lead: dict[str, Any]) -> float:
        """Transparent fallback when no artifact is present.

        Deliberately not zero or a constant: an all-equal score makes the Leads
        list unsortable and reads as a broken feature. Ranks on the one
        firmographic that carried real signal historically — lead source, where
        customer referrals convert at 43% against cold email's 17%.
        """

        source = (lead.get("lead_source") or "").strip().lower()
        by_source = {
            "customer referral": 0.43,
            "partner referral": 0.40,
            "inbound - web form": 0.35,
            "inbound - content download": 0.30,
            "event / conference": 0.27,
            "paid search": 0.25,
            "outbound - sdr": 0.20,
            "cold email": 0.17,
        }
        return by_source.get(source, 0.29)

    def _explanation(
        self,
        *,
        score: int,
        probability: float,
        icp_adjustment: float,
        signal_adjustment: float,
        trained: bool,
        metrics: dict[str, Any],
    ) -> str:
        parts = [
            f"Score {score}/100.",
            f"Historical fit for companies like this: {probability:.0%}.",
        ]
        if round(icp_adjustment, 1):
            direction = "raised" if icp_adjustment > 0 else "lowered"
            parts.append(f"ICP fit {direction} it by {abs(icp_adjustment):.0f}.")
        if round(signal_adjustment, 1):
            parts.append(f"Buying signals added {signal_adjustment:.0f}.")
        if trained:
            lift = metrics.get("lift_top_10pct")
            if lift:
                parts.append(
                    f"Model ranks {lift}x better than random in the top decile "
                    f"(AUC {metrics.get('roc_auc')})."
                )
        else:
            parts.append("No trained model available — using a source-based fallback.")
        return " ".join(parts)
