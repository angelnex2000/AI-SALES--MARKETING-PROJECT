import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Tracks a background AI task so the frontend can poll GET /jobs/{id}
    instead of blocking a request on a slow agent call (research, scoring,
    forecasting). Not in the original folder tree — added because the
    request flow (POST /leads/{id}/research -> job -> poll) has nowhere
    else to persist status/result/error.
    """

    __tablename__ = "jobs"

    job_type: Mapped[str] = mapped_column(String)
    """e.g. lead_intelligence, outreach_draft, revenue_forecast"""
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    status: Mapped[JobStatus] = mapped_column(default=JobStatus.PENDING, index=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)