import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MeetingStatus(str, Enum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class MeetingType(str, Enum):
    """A meeting is a sales milestone, not just a calendar entry — the type is
    what makes "3 demos booked this week" answerable."""

    DISCOVERY = "discovery"
    DEMO = "demo"
    FOLLOW_UP = "follow_up"
    NEGOTIATION = "negotiation"
    OTHER = "other"


class Meeting(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "meetings"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    """Which person at the lead company is attending. Nullable — a slot can be
    booked before the attendee is confirmed."""
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String, default="Meeting")
    meeting_type: Mapped[MeetingType] = mapped_column(default=MeetingType.DEMO, index=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    """Required. Without an end time there is no duration, so availability
    cannot be computed, double-bookings cannot be detected, and no calendar
    event can be created — yet /availability and /suggest-slots both exist."""
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    """Room, dial-in, or meeting URL once the calendar integration fills it in."""
    status: Mapped[MeetingStatus] = mapped_column(default=MeetingStatus.SCHEDULED, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    """Set once by record_outcome; its presence is what makes recording an
    outcome idempotent."""
    next_action: Mapped[str | None] = mapped_column(String, nullable=True)
