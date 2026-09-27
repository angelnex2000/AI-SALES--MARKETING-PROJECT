"""Explanation contracts.

A `Factor` is one reason the score is what it is. Every factor carries the
**measured** contribution it made, not a label someone attached by hand — see
`explainer.py` for why that distinction is the whole point of this module.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class FactorSource(str, Enum):
    """Where a factor's number came from, so the UI and any auditor can tell
    a measured attribution from an arithmetic one."""

    MODEL = "model"
    """Measured by ablating the feature and re-running the model."""
    COMPONENT = "component"
    """An exact term of the composed score (ICP or signal adjustment)."""


class Factor(BaseModel):
    label: str
    """Plain language, for a salesperson — not a feature name."""
    impact: float
    """Score points contributed. Signed: negative means it pushed the score
    down. Summing all factors approximates the distance from the baseline."""
    source: FactorSource
    detail: str | None = None
    """The underlying feature or component, for debugging and the AI Center."""


class ScoreExplanation(BaseModel):
    # `model_version` collides with pydantic's reserved `model_` prefix. The
    # field name is part of the AI-output contract everywhere else in this
    # codebase, so disable the check rather than rename it here.
    model_config = ConfigDict(protected_namespaces=())

    lead_score: int
    confidence: float
    baseline_score: int
    """What an otherwise-identical lead with no distinguishing attributes
    scores. Without it, "+8 for industry" has no reference point."""
    positive_factors: list[Factor] = Field(default_factory=list)
    negative_factors: list[Factor] = Field(default_factory=list)
    recommendation: str
    model_version: str
    summary: str
