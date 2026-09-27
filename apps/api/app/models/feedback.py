import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from agents.feedback_learning.loss_reasons import LossReason
from app.models.base import (
    Base,
    JSONColumn,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class Outcome(str, Enum):
    WON = "won"
    LOST = "lost"


class DealOutcome(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """First-class model, not a field on Lead — the Feedback Learning Agent
    reads this table directly to retrain scoring/outreach models. Loss
    reason is always a structured enum (see agents/feedback_learning/
    loss_reasons.py), never free text, so it stays usable for retraining."""

    __tablename__ = "deal_outcomes"

    deal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deals.id"), index=True)
    """Keyed to the DEAL, not the lead (Phase 5 Module 5 reversal, closed here).
    One lead can hold several opportunities — an upsell that closed won and a
    renewal that closed lost. Keyed by lead_id those two outcomes were
    indistinguishable, so the Feedback Learning Agent could not tell which
    opportunity a loss_reason belonged to and would retrain on mislabelled
    examples."""
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    """Denormalised from the deal. Kept because feedback learning aggregates
    per-account win rates and this avoids a join on every training pull; it is
    derived from Deal.lead_id and must never be set independently."""
    outcome: Mapped[Outcome] = mapped_column()
    loss_reason: Mapped[LossReason | None] = mapped_column(nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeedbackTarget(str, Enum):
    """Which AI output a piece of feedback is about.

    Polymorphic (`target_type` + `target_id`) rather than one nullable FK per
    AI table. Module 13 collects feedback on seven different outputs, and seven
    nullable foreign keys plus a CHECK that exactly one is set is a worse
    trade than losing referential integrity here — especially since every AI
    output table is append-only and never deletes rows, so orphans do not
    arise. `feedback_service` validates that the target exists and belongs to
    the tenant before writing.
    """

    EMAIL_DRAFT = "email_draft"
    RESEARCH_REPORT = "research_report"
    LEAD_SCORE = "lead_score"
    BUYING_SIGNAL = "buying_signal"
    ICP_SCORE = "icp_score"
    REPLY_INTENT = "reply_intent"
    REVENUE_FORECAST = "revenue_forecast"


class FeedbackVerdict(str, Enum):
    HELPFUL = "helpful"
    NEEDS_WORK = "needs_work"
    INCORRECT = "incorrect"


class FeedbackRecord(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """**Explicit** human feedback on one AI output.

    Deliberately stores only what cannot be derived. The module brief's version
    carries `edited`, `meeting_booked` and `deal_closed` booleans, and all
    three already exist as first-class facts elsewhere: the edit is
    `EmailDraft.ai_original_body` versus `body`, the meeting is a `Meeting`
    row, the outcome is a `DealOutcome`. Copying them here creates a second
    source of truth that goes stale the moment a meeting is cancelled or a deal
    reopens — and this is the table a future retraining run reads, so a stale
    label is not a display bug, it is a mislabelled training example. Outcomes
    are joined at read time by `feedback_service` instead.

    (The brief also names a column `metadata`. That cannot be built: SQLAlchemy
    reserves `metadata` on a declarative class and raises `InvalidRequestError`
    at import. It is `details` here.)
    """

    __tablename__ = "feedback_records"

    target_type: Mapped[FeedbackTarget] = mapped_column(index=True)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    """The AI output row this is about. No FK — see FeedbackTarget."""
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True, index=True
    )
    """Denormalised so feedback can be shown on a lead's timeline without
    resolving the polymorphic target first. Null for company-level outputs like
    a revenue forecast, which belong to no lead."""
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    """Required: this is explicit feedback, so somebody gave it. Contrast
    `CRMActivity.actor_id`, which is nullable because the platform generates
    activity with no human author."""
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """1-5, validated in the schema layer."""
    verdict: Mapped[FeedbackVerdict | None] = mapped_column(nullable=True)
    correction: Mapped[str | None] = mapped_column(String, nullable=True)
    """What the answer should have been — e.g. the right `ReplyIntent` label.
    This is the only feedback that yields a supervised training pair, which is
    why it is a column rather than free text in `comment`."""
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)