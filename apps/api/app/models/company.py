from enum import Enum
from typing import Any

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONColumn, TimestampMixin, UUIDPrimaryKeyMixin


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
    icp_config: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """Who *this tenant* sells to — target industries, size bands, regions and
    scoring weights. **Must be per-tenant.** ICP criteria hardcoded into shared
    agent code would score a German logistics vendor's leads against a
    healthcare-in-India profile; every tenant would be told their best leads
    are whichever ones happen to match someone else's business.

    Null means "use `agents/icp_matching/rules.py::DEFAULT_ICP`", so a new
    workspace scores sensibly before anyone configures anything. Edited from
    the AI Center (scoring-weight config). Shape is validated by
    `rules.resolve_profile()`, not by the column."""
    scheduling_config: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """Working hours, working days, timezone and notice period for the Meeting
    Scheduler. **Per-tenant for the same reason as `icp_config`** — a German
    logistics vendor and an Indian health-tech startup share neither a working
    day nor a weekend — but with a sharper failure mode: every datetime in this
    system is stored in UTC, so "10:00–18:00" without a timezone offers an
    Indian rep meetings from 15:30 to 23:30 local.

    Null means "use `agents/meeting_scheduler/rules.py::DEFAULT_SCHEDULING`",
    whose timezone default is **UTC rather than a guess** — slots that are
    visibly labelled UTC are fixable, slots silently computed against someone
    else's country are not. Validated by `rules.resolve_config()`."""