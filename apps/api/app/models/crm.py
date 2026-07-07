import uuid

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class CRMActivity(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Human-logged interactions — feeds the Lead Details Activities tab.
    Distinct from Timeline, which merges this with AI outputs and system
    events into one narrative view (computed, not a separate table).
    Carries company_id directly so tenant isolation holds without a join
    through Lead."""

    __tablename__ = "crm_activities"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    activity_type: Mapped[str] = mapped_column(String)
    """e.g. call, email_sent, status_change, meeting_scheduled"""
    description: Mapped[str] = mapped_column(Text)


class Note(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Free-text, human-authored only — never AI-generated. Kept separate
    from CRMActivity because it's unstructured and personal, feeding the
    Lead Details Notes tab specifically."""

    __tablename__ = "notes"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)