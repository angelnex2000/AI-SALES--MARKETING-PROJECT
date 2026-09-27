"""CRM history: activities and notes.

Two different things that look similar:

  * **Activities** are timeline events — mostly system-generated (lead created,
    AI research finished, email sent, deal moved to Proposal). They are
    **append-only**: there is no update or delete, because rewriting history
    would make the Timeline tab and any audit built on it untrustworthy.
  * **Notes** are free text written by a person. They are editable, but only
    by their author — see `update_note`.

Both are reachable only through a lead the caller can already see, so every
function re-runs the lead isolation gate.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.crm import CRMActivity, Note
from app.models.deal import Deal
from app.models.user import Role, User
from app.services import lead_service


async def _check_deal_belongs_to_lead(
    db: AsyncSession, *, deal_id: uuid.UUID | None, lead_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    """A note or activity may be attached to a deal, but only one belonging to
    the same lead — otherwise history could be filed against an unrelated
    opportunity, including one the caller cannot see."""

    if deal_id is None:
        return
    stmt = select(Deal).where(
        Deal.id == deal_id,
        Deal.company_id == company_id,
        Deal.lead_id == lead_id,
        Deal.archived_at.is_(None),
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise ValidationError(
            "deal_id does not belong to this lead", error_code="DEAL_LEAD_MISMATCH"
        )


# ------------------------------------------------------------------ activities


async def list_activities(
    db: AsyncSession, *, lead_id: uuid.UUID, current_user: User
) -> list[CRMActivity]:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    stmt = (
        select(CRMActivity)
        .where(CRMActivity.company_id == current_user.company_id, CRMActivity.lead_id == lead_id)
        .order_by(CRMActivity.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_activity(
    db: AsyncSession, *, lead_id: uuid.UUID, data: dict, current_user: User
) -> CRMActivity:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    await _check_deal_belongs_to_lead(
        db, deal_id=data.get("deal_id"), lead_id=lead_id, company_id=current_user.company_id
    )
    activity = CRMActivity(
        company_id=current_user.company_id, lead_id=lead_id, actor_id=current_user.id, **data
    )
    db.add(activity)
    await db.commit()
    await db.refresh(activity)
    return activity


# ----------------------------------------------------------------------- notes


async def list_notes(db: AsyncSession, *, lead_id: uuid.UUID, current_user: User) -> list[Note]:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    stmt = (
        select(Note)
        .where(Note.company_id == current_user.company_id, Note.lead_id == lead_id)
        .order_by(Note.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def create_note(
    db: AsyncSession, *, lead_id: uuid.UUID, data: dict, current_user: User
) -> Note:
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    await _check_deal_belongs_to_lead(
        db, deal_id=data.get("deal_id"), lead_id=lead_id, company_id=current_user.company_id
    )
    note = Note(
        company_id=current_user.company_id, lead_id=lead_id, author_id=current_user.id, **data
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def _require_note(db: AsyncSession, *, note_id: uuid.UUID, current_user: User) -> Note:
    stmt = select(Note).where(Note.id == note_id, Note.company_id == current_user.company_id)
    note = (await db.execute(stmt)).scalar_one_or_none()
    if note is None:
        raise NotFoundError("Note not found", error_code="NOTE_NOT_FOUND")
    # The flat /notes/{id} route carries no lead_id, so re-run the lead gate —
    # otherwise a Sales Exec could reach a note on someone else's lead.
    await lead_service.require_lead(
        db, lead_id=note.lead_id, company_id=current_user.company_id, current_user=current_user
    )
    return note


async def update_note(
    db: AsyncSession, *, note_id: uuid.UUID, body: str, current_user: User
) -> Note:
    note = await _require_note(db, note_id=note_id, current_user=current_user)
    # Author only, and deliberately not overridable by a manager: the note
    # keeps displaying its author's name, so letting someone else rewrite the
    # text would put words in that person's mouth.
    if note.author_id != current_user.id:
        raise ForbiddenError("Only the author can edit a note", error_code="NOT_NOTE_AUTHOR")
    note.body = body
    await db.commit()
    await db.refresh(note)
    return note


async def delete_note(db: AsyncSession, *, note_id: uuid.UUID, current_user: User) -> None:
    note = await _require_note(db, note_id=note_id, current_user=current_user)
    # Removing a note is not the same as rewriting it: a Sales Manager may
    # delete anyone's (moderation), but a rep may only delete their own.
    if note.author_id != current_user.id and current_user.role != Role.SALES_MANAGER:
        raise ForbiddenError(
            "Only the author or a Sales Manager can delete a note", error_code="NOT_NOTE_AUTHOR"
        )
    # Hard delete is safe here: nothing references notes.id, and a note is
    # personal text rather than a record other data depends on.
    await db.delete(note)
    await db.commit()


async def log_system_activity(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    lead_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    activity_type: str,
    description: str,
    deal_id: uuid.UUID | None = None,
) -> CRMActivity:
    """For activity the platform records itself (email sent, stage moved, AI
    research completed). Skips the isolation gate on purpose — callers are
    internal services that have already resolved the lead — so never expose
    this directly to a router.
    """

    activity = CRMActivity(
        company_id=company_id,
        lead_id=lead_id,
        deal_id=deal_id,
        actor_id=actor_id,
        activity_type=activity_type,
        description=description,
    )
    db.add(activity)
    return activity


__all__ = [
    "create_activity",
    "create_note",
    "delete_note",
    "list_activities",
    "list_notes",
    "log_system_activity",
    "update_note",
]

# Deliberately absent: update_activity / delete_activity. Activities are an
# append-only event log; correcting one means logging a new event.
