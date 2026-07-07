import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class IntegrationType(str, Enum):
    CRM = "crm"
    EMAIL = "email"
    CALENDAR = "calendar"
    CHAT = "chat"


class IntegrationProvider(str, Enum):
    SALESFORCE = "salesforce"
    HUBSPOT = "hubspot"
    ZOHO = "zoho"
    GMAIL = "gmail"
    GOOGLE_CALENDAR = "google_calendar"
    SLACK = "slack"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class Integration(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One per tenant's connected external tool — CRM, email, calendar, or
    chat (generalized from a CRM-only model, since the Integrations page has
    covered Gmail/Calendar/Slack since the Phase 2 wireframes). OAuth tokens
    are encrypted at rest via core/security.py::encrypt_secret — never
    stored, logged, or sent to the frontend in plaintext."""

    __tablename__ = "integrations"

    integration_type: Mapped[IntegrationType] = mapped_column()
    provider: Mapped[IntegrationProvider] = mapped_column()
    status: Mapped[ConnectionStatus] = mapped_column(default=ConnectionStatus.DISCONNECTED)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class IntegrationSyncLog(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "integration_sync_logs"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integrations.id"), index=True
    )
    sync_type: Mapped[str] = mapped_column(String)
    """e.g. lead_import, activity_push, contact_sync, calendar_sync"""
    status: Mapped[SyncStatus] = mapped_column()
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)