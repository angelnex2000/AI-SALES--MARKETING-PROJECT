from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Role(str, Enum):
    """Fixed set of four roles (Phase 4 Module 2 decision: no dynamic
    roles/permissions tables). require_role() enforces against this enum —
    it is the actual authorization mechanism, not a DB lookup."""

    ADMIN = "admin"
    SALES_MANAGER = "sales_manager"
    SALES_EXECUTIVE = "sales_executive"
    MARKETING = "marketing"


class User(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    full_name: Mapped[str] = mapped_column(String)
    role: Mapped[Role] = mapped_column(default=Role.SALES_EXECUTIVE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)