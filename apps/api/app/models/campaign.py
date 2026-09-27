import uuid
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    JSONColumn,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class CampaignStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"


class TemplateStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Campaign(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "campaigns"

    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    target_industry: Mapped[str | None] = mapped_column(String, nullable=True)
    target_region: Mapped[str | None] = mapped_column(String, nullable=True)
    goal: Mapped[str | None] = mapped_column(String, nullable=True)
    """e.g. book_demos, drive_signups, re_engage"""
    status: Mapped[CampaignStatus] = mapped_column(default=CampaignStatus.DRAFT)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class CampaignTemplate(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Reusable across campaigns — deliberately NOT tied to a single
    campaign_id, so a successful message can be reused and versioned."""

    __tablename__ = "campaign_templates"

    name: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[TemplateStatus] = mapped_column(default=TemplateStatus.DRAFT)


class AudienceSegment(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Who a campaign targets, and the plan for reaching them.

    The selection criteria and the resulting plan live here rather than in a
    separate `campaign_recommendations` table: this row already *is* "who this
    campaign is for", and a parallel table would let the two disagree about
    the same campaign.
    """

    __tablename__ = "audience_segments"

    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"), index=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    min_employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    region: Mapped[str | None] = mapped_column(String, nullable=True)
    criteria: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """Thresholds actually used, stored so a campaign remains reproducible
    after the tenant changes their defaults."""
    selected_lead_ids: Mapped[list[str] | None] = mapped_column(JSONColumn, nullable=True)
    """A **snapshot**, not a saved query. Re-running the query at send time
    would silently change the audience between approval and delivery — a
    marketing lead approves a list of 42 and 300 receive it."""
    strategy: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """The Campaign Agent's plan: tone, CTA, sequence length, and the case
    study RAG actually returned (never one the agent named itself)."""
    planned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)