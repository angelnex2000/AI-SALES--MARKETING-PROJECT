import uuid
from enum import Enum
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AuditCategory(str, Enum):
    BUSINESS = "business"
    SECURITY = "security"


class AuditLog(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Platform-wide 'who did what, when' — one table with a category
    rather than a separate business-audit table and security-log table,
    which would inevitably drift out of sync with each other.

    entity_type/entity_id + old_value/new_value give real before/after diff
    tracking ('lead #123: status contacted -> proposal'). `details` remains
    for events that aren't a clean diff (a failed login has no old/new value
    but still needs context)."""

    __tablename__ = "audit_logs"

    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    category: Mapped[AuditCategory] = mapped_column(default=AuditCategory.BUSINESS, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    """e.g. lead.assigned, login.failed, integration.credentials_updated"""
    entity_type: Mapped[str | None] = mapped_column(String, nullable=True)
    """e.g. lead, user, integration, campaign"""
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)