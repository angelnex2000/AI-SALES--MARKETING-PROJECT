from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionStatus(str, Enum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class BillingSubscription(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One active subscription per tenant. user_limit and ai_credit_limit
    are enforced against UsageRecord to gate seats and AI usage per plan."""

    __tablename__ = "billing_subscriptions"

    plan_name: Mapped[str] = mapped_column(String)
    status: Mapped[SubscriptionStatus] = mapped_column(default=SubscriptionStatus.TRIALING)
    monthly_price: Mapped[float] = mapped_column(Float, default=0.0)
    user_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_credit_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageRecord(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Metered usage for billing and plan-limit enforcement — e.g. AI
    research reports generated, emails drafted, CRM syncs run."""

    __tablename__ = "usage_records"

    usage_type: Mapped[str] = mapped_column(String, index=True)
    """e.g. ai_research_report, email_generated, crm_sync"""
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    billing_period: Mapped[str] = mapped_column(String, index=True)
    """e.g. 2026-07 — the period this usage counts against."""