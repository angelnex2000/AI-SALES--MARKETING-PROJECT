import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# JSONB on Postgres, plain JSON on SQLite. Without the variant the schema
# cannot be created off Postgres at all — `CompileError: can't render element
# of type JSONB` — which made the whole test suite impossible to run locally.
# Use this everywhere instead of importing JSONB directly.
JSONColumn = JSONB().with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    # Persist enums by VALUE, not by name. SQLAlchemy's default stores
    # `Role.SALES_EXECUTIVE` as "SALES_EXECUTIVE", but every other layer —
    # the JWT role claim, require_role(), the frontend's nav rules, the
    # documented API contract — uses "sales_executive". Without this, the
    # database is the one place holding a different spelling, so raw SQL,
    # analytics queries, seed scripts, and CRM syncs all silently miss.
    # Declared once here so all 21 enum columns stay consistent.
    type_annotation_map = {
        enum.Enum: SAEnum(enum.Enum, values_callable=lambda e: [member.value for member in e]),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TenantMixin:
    """Every tenant-scoped table carries company_id. This column existing is
    not what enforces isolation — every query in every service must filter
    by it (see lead_service.py). A user from Company A must never be able
    to construct a query that returns Company B's rows.
    """

    @declared_attr
    def company_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False, index=True)