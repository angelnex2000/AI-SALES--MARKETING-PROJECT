"""Lead business logic.

Routers receive requests; this module makes the decisions. Everything that
answers "is this caller allowed to see or change this lead, and what happens
when they do" lives here, so no router can accidentally skip a rule.

There is deliberately no repository layer — the SQLAlchemy queries live here
(Phase 7 Module 2 decision). Tenant filtering is therefore one visible rule
per function rather than something split across two layers.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.lead import Lead
from app.models.user import Role, User


def _visible(stmt: Select, *, company_id: uuid.UUID, current_user: User) -> Select:
    """The isolation rules, applied together in one place.

    Tenant isolation and assigned-leads-only are enforced here, not just
    hidden in the UI: a Sales Executive querying this never sees another
    rep's leads, and no query can cross a company_id boundary. Archived
    leads are excluded — they exist only so their AI history stays valid.
    """

    stmt = stmt.where(Lead.company_id == company_id, Lead.archived_at.is_(None))
    if current_user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == current_user.id)
    return stmt


async def list_leads(db: AsyncSession, *, company_id: uuid.UUID, current_user: User) -> list[Lead]:
    stmt = _visible(select(Lead), company_id=company_id, current_user=current_user)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, company_id: uuid.UUID, current_user: User
) -> Lead | None:
    stmt = _visible(
        select(Lead).where(Lead.id == lead_id), company_id=company_id, current_user=current_user
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def require_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, company_id: uuid.UUID, current_user: User
) -> Lead:
    """404, never 403 — a Sales Exec reaching an unassigned lead must not
    learn that it exists."""

    lead = await get_lead(db, lead_id=lead_id, company_id=company_id, current_user=current_user)
    if lead is None:
        raise NotFoundError("Lead not found", error_code="LEAD_NOT_FOUND")
    return lead


async def create_lead(db: AsyncSession, *, data: dict, current_user: User) -> Lead:
    lead = Lead(company_id=current_user.company_id, **data)
    # A Sales Exec who adds a prospect owns it immediately — otherwise they
    # would create a lead and instantly lose sight of it under assigned-only.
    if current_user.role == Role.SALES_EXECUTIVE:
        lead.owner_id = current_user.id
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


async def update_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, changes: dict, current_user: User
) -> Lead:
    lead = await require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    for field, value in changes.items():
        setattr(lead, field, value)
    await db.commit()
    await db.refresh(lead)
    return lead


async def archive_lead(db: AsyncSession, *, lead_id: uuid.UUID, current_user: User) -> None:
    """Soft delete. See Lead.archived_at for why this is never a real DELETE."""

    lead = await require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    lead.archived_at = datetime.now(UTC)
    await db.commit()


async def assign_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, owner_user_id: uuid.UUID, current_user: User
) -> Lead:
    """Gate 1. Only a Sales Manager reaches here (enforced by require_role at
    the router), and only a Sales Executive in the same company may receive
    the lead."""

    lead = await require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    owner = await db.get(User, owner_user_id)
    # db.get is a primary-key fetch with no tenant filter, so this company
    # check is what stops a lead being handed to another tenant's user.
    if owner is None or owner.company_id != current_user.company_id:
        raise NotFoundError("Assignee not found", error_code="USER_NOT_FOUND")
    if owner.role != Role.SALES_EXECUTIVE:
        raise ForbiddenError("Leads can only be assigned to a Sales Executive")
    lead.owner_id = owner.id
    await db.commit()
    await db.refresh(lead)
    return lead
