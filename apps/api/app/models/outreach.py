import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from agents.reply_intent.labels import ReplyIntent
from app.models.base import (
    Base,
    JSONColumn,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.models.lead import AIOutputMixin


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

    # Reproducibility. A customer complaint about a claim in a sent email has
    # to be traceable to the exact model, instructions and documents that
    # produced it — and a drop in reply rates has to be attributable to
    # whichever of the three changed.
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    """Prompt wording moves output as much as a model swap does; without this
    a regression is untraceable."""
    rag_sources: Mapped[list[str] | None] = mapped_column(JSONColumn, nullable=True)
    """`knowledge_chunks.id` values the draft actually cited — the audit trail
    behind every claim it makes."""
    ai_original_subject: Mapped[str | None] = mapped_column(String, nullable=True)
    ai_original_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    """What the Outreach Agent actually wrote, snapshotted by
    `outreach_service.update_draft` the first time a human changes the draft.

    **Without these the platform's best feedback signal does not exist.**
    Editing overwrites `subject`/`body` in place, so the AI's words were
    destroyed by the first keystroke and Module 13's edit distance would have
    compared an edited draft against itself — reporting a flattering 0.0 for
    every draft, forever. Null means nobody has edited it: an unedited approved
    draft is the strongest positive signal there is, not missing data.

    Snapshotted on first edit rather than at creation so it captures the last
    fully-AI state regardless of which code path produced the row, and stays
    fixed across later edits — the metric wanted is total human divergence from
    the AI, not the size of the most recent keystroke."""
    validation_findings: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONColumn, nullable=True
    )
    """Structural problems found before review. Present so the approval UI
    leads with them; they do **not** gate approval, because a human editing
    and approving a flagged draft is a legitimate path."""
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )


class SentEmail(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "sent_emails"

    draft_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("email_drafts.id"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_address: Mapped[str | None] = mapped_column(String, nullable=True)
    """The address the message actually went to, captured at send time rather
    than resolved through `draft.contact_id` later — a contact's email can be
    corrected afterwards, and "who did we email" must not change retroactively."""
    delivery_status: Mapped[str] = mapped_column(String, default="dry_run", index=True)
    """`dry_run` | `sent` | `failed`. A plain String, not a DB enum, for the
    same reason as `signal_type`: provider states grow (queued, bounced,
    deferred, complained) and an enum would mean a migration per addition.

    **`dry_run` is the default**, so a row that was never actually delivered can
    never be mistaken for one that was — which matters most for the very first
    real send, when it is easy to assume the pipeline worked because the row
    appeared."""
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)
    """Mailjet's id for the message. The join key for a future delivery/bounce
    webhook, and what support asks for when a customer says nothing arrived."""
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)


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


class ReplyIntentResult(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    """Reply Intent Agent output for one Reply. Separate table (not columns
    on Reply) so re-classification with a newer model keeps history.
    Named to avoid colliding with the ReplyIntent enum in
    agents/reply_intent/labels.py.

    Carries AIOutputMixin rather than hand-rolling three of its four columns,
    which is how it previously ended up without `explanation` — the one field
    that matters most here. The suggested action can be `mark_closed_lost`,
    and a rep asked to close a deal on an AI's say-so has to be able to see
    which sentence produced it."""

    __tablename__ = "reply_intent_results"

    reply_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("replies.id"), index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    intent: Mapped[ReplyIntent] = mapped_column()
    suggested_action: Mapped[str | None] = mapped_column(String, nullable=True)
    """A suggestion rendered as a button, never an executed action. Stays a
    String, not a DB enum, for the same reason `BuyingSignal.signal_type`
    does — the action list grows with the UI."""
    matched_phrase: Mapped[str | None] = mapped_column(String, nullable=True)
    """The words the classification was read from. Null for `unknown` and for
    a future model-based classifier with no single anchoring phrase."""
    alternative_intents: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONColumn, nullable=True
    )
    """Other readings that fit. Real replies ask for two things at once
    ("send pricing before we book a demo"); collapsing that to one label
    silently drops half of what the customer asked for."""