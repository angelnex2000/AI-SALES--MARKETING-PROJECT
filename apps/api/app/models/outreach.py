import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from agents.reply_intent.labels import ReplyIntent
from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DraftStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    SENT = "sent"


class EmailDraft(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Gate 2 lives here: a draft only becomes a SentEmail once a Sales
    Executive approves it. No code path should ever send() directly from
    AI output."""

    __tablename__ = "email_drafts"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contacts.id"), nullable=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    subject: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    ai_generated: Mapped[bool] = mapped_column(default=True)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[DraftStatus] = mapped_column(default=DraftStatus.PENDING_APPROVAL, index=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class SentEmail(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "sent_emails"

    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("email_drafts.id"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Reply(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """The raw inbound message. Its AI classification lives in a separate
    ReplyIntentResult row — same principle as LeadScore/ICPScore: AI output
    is append-only history, not a mutable field on the parent record."""

    __tablename__ = "replies"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    sent_email_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sent_emails.id"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text)


class ReplyIntentResult(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Reply Intent Agent output for one Reply. Separate table (not columns
    on Reply) so re-classification with a newer model keeps history.
    Named to avoid colliding with the ReplyIntent enum in
    agents/reply_intent/labels.py."""

    __tablename__ = "reply_intent_results"

    reply_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("replies.id"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    intent: Mapped[ReplyIntent] = mapped_column()
    confidence: Mapped[float] = mapped_column()
    suggested_action: Mapped[str | None] = mapped_column(String, nullable=True)
    model_name: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)