import uuid
from datetime import datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DealStage(str, Enum):
    """Fixed pipeline stage enum — no per-tenant `pipeline_stages` table.

    Phase 5 Module 5 reversal: pipeline stages moved OFF `Lead.status` (which
    reduces to a lead lifecycle) and onto the Deal, because a prospect account
    can now hold multiple opportunities (upsell / renewal / re-engagement).
    """

    NEW = "new"
    QUALIFIED = "qualified"
    DEMO_SCHEDULED = "demo_scheduled"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class Deal(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A qualified revenue opportunity against a Lead. 1 Lead : N Deal.

    Owner is NOT stored here — it derives from the parent lead's `owner_id`,
    keeping a single assignment gate (Gate 1). Revenue Forecasting reads
    `amount`/`expected_close_date` from this table, not from Lead. Closed-lost
    outcomes are recorded per-deal in `deal_outcomes` with an enum reason.
    """

    __tablename__ = "deals"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    name: Mapped[str] = mapped_column(String)
    stage: Mapped[DealStage] = mapped_column(default=DealStage.NEW, index=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    """NUMERIC, never Float. Money in binary floating point cannot represent
    values like 0.10 exactly, and this column is summed across a whole pipeline
    to produce revenue forecasts — float error compounds with every deal. 14,2
    holds up to 999,999,999,999.99 in any currency."""
    currency: Mapped[str] = mapped_column(String, default="USD")
    """ISO 4217. Amounts in different currencies must never be summed without
    conversion — see the note in deal_service.pipeline_board."""
    expected_close_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    """Soft delete, same rule as Lead/Contact. `deal_outcomes.deal_id`
    references this row, and destroying a won/lost outcome would silently
    remove a training example from the Feedback Learning Agent."""
