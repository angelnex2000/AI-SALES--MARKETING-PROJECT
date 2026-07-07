import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from agents.feedback_learning.loss_reasons import LossReason
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Outcome(str, Enum):
    WON = "won"
    LOST = "lost"


class DealOutcome(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """First-class model, not a field on Lead — the Feedback Learning Agent
    reads this table directly to retrain scoring/outreach models. Loss
    reason is always a structured enum (see agents/feedback_learning/
    loss_reasons.py), never free text, so it stays usable for retraining."""

    __tablename__ = "deal_outcomes"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    outcome: Mapped[Outcome] = mapped_column()
    loss_reason: Mapped[LossReason | None] = mapped_column(nullable=True)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)