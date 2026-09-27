"""Contact business logic.

A Lead is the prospect *company*; a Contact is a person inside it. Contacts
carry their own `company_id` rather than relying on a join through Lead, so
the tenant filter is applied directly here.

Every function takes the caller and re-runs the lead-level isolation check
via `lead_service.require_lead`, because a contact is only reachable if its
parent lead is — including the assigned-only rule for Sales Executives.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.lead import Contact
from app.models.user import User
from app.services import lead_service


def _visible(stmt: Select, *, company_id: uuid.UUID) -> Select:
    return stmt.where(Contact.company_id == company_id, Contact.archived_at.is_(None))


async def list_for_lead(db: AsyncSession, *, lead_id: uuid.UUID, current_user: User) -> list[Contact]:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    stmt = _visible(select(Contact).where(Contact.lead_id == lead_id), company_id=current_user.company_id)
    result = await db.execute(stmt.order_by(Contact.is_primary.desc(), Contact.full_name))
    return list(result.scalars().all())


async def require_contact(db: AsyncSession, *, contact_id: uuid.UUID, current_user: User) -> Contact:
    """Flat /contacts/{id} routes carry no lead_id, so re-derive the parent
    lead and re-run its isolation check before allowing a write."""

    stmt = _visible(select(Contact).where(Contact.id == contact_id), company_id=current_user.company_id)
    contact = (await db.execute(stmt)).scalar_one_or_none()
    if contact is None:
        raise NotFoundError("Contact not found", error_code="CONTACT_NOT_FOUND")
    # Assignment recheck: a Sales Exec must not reach a contact belonging to a
    # lead that isn't theirs, even though the contact row is in their tenant.
    await lead_service.require_lead(
        db, lead_id=contact.lead_id, company_id=current_user.company_id, current_user=current_user
    )
    return contact


async def _demote_other_primaries(
    db: AsyncSession, *, lead_id: uuid.UUID, company_id: uuid.UUID, except_id: uuid.UUID | None = None
) -> None:
    """At most one primary contact per lead. Scoped by company_id as well as
    lead_id — defence in depth, so this can never touch another tenant even if
    a caller passes a lead_id it shouldn't have."""

    stmt = _visible(
        select(Contact).where(Contact.lead_id == lead_id, Contact.is_primary.is_(True)),
        company_id=company_id,
    )
    for other in (await db.execute(stmt)).scalars().all():
        if except_id is None or other.id != except_id:
            other.is_primary = False


async def create_contact(
    db: AsyncSession, *, lead_id: uuid.UUID, data: dict, current_user: User
) -> Contact:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    contact = Contact(company_id=current_user.company_id, lead_id=lead_id, **data)
    if contact.is_primary:
        await _demote_other_primaries(db, lead_id=lead_id, company_id=current_user.company_id)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


async def update_contact(
    db: AsyncSession, *, contact_id: uuid.UUID, changes: dict, current_user: User
) -> Contact:
    contact = await require_contact(db, contact_id=contact_id, current_user=current_user)
    if changes.get("is_primary"):
        await _demote_other_primaries(
            db,
            lead_id=contact.lead_id,
            company_id=current_user.company_id,
            except_id=contact.id,
        )
    for field, value in changes.items():
        setattr(contact, field, value)
    await db.commit()
    await db.refresh(contact)
    return contact


async def archive_contact(db: AsyncSession, *, contact_id: uuid.UUID, current_user: User) -> None:
    contact = await require_contact(db, contact_id=contact_id, current_user=current_user)
    contact.archived_at = datetime.now(UTC)
    # A departed contact must not stay flagged as the lead's primary point of
    # contact, or the lead looks like it still has one.
    contact.is_primary = False
    await db.commit()
