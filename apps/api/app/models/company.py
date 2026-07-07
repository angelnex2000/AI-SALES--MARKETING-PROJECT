from enum import Enum

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class CompanyStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"


class Company(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A SaaS tenant — one of our paying customers. Never to be confused with
    `Lead`, which is a prospect company that a tenant is pursuing.
    """

    __tablename__ = "companies"

    name: Mapped[str] = mapped_column(index=True)
    industry: Mapped[str | None] = mapped_column(nullable=True)
    website: Mapped[str | None] = mapped_column(nullable=True)
    plan: Mapped[str] = mapped_column(default="starter")
    status: Mapped[CompanyStatus] = mapped_column(default=CompanyStatus.ACTIVE)