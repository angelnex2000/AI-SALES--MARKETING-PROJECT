from decimal import Decimal
from typing import Any

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONColumn, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.lead import AIOutputMixin


class RevenueForecast(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    """Revenue Forecasting Agent output — company-scoped (a forecast is over
    the whole pipeline for a period), not lead-scoped. Append-only history so
    forecast accuracy can be evaluated after the period closes.

    Carries `AIOutputMixin` so `explanation` sits alongside
    model_name/model_version/confidence. On this table that field is the
    difference between a number and a defensible number: it is what a Sales
    Manager quotes upward, and "why is it that?" must have an answer that is
    not "the model said so".
    """

    __tablename__ = "revenue_forecasts"

    forecast_period: Mapped[str] = mapped_column(String, index=True)
    """e.g. 2026-07 (month) or 2026-Q3 (quarter)"""
    currency: Mapped[str] = mapped_column(String, default="USD")
    """ISO 4217. **One forecast row per (period, currency)** — a tenant selling
    in INR and USD gets two rows, never one summed figure. There is no FX
    source in this service, so adding them produces a number that is not money;
    the same rule `deal_service.pipeline_board` follows with
    `totals_by_currency`."""
    predicted_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    """NUMERIC, never Float — this is money, summed from `Deal.amount` across a
    whole pipeline. It was a `Float` until Module 12 made the column live,
    which contradicted the rule `Deal.amount` exists to enforce. Wider than
    `Deal.amount`'s 14,2 because it holds their sum."""
    committed_revenue: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    """Already closed-won inside the period. Split out from the weighted part
    because the two carry completely different certainty: this is banked, the
    rest is an expectation over deals that have not happened yet."""
    weighted_pipeline: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=Decimal("0"))
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """Per-stage rollup, top contributing deals, excluded pipeline, and the
    trend against the previous period — what the dashboard renders, and what
    makes the headline figure auditable after the period closes."""
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Snapshot of the pipeline inputs the forecast was computed from."""
