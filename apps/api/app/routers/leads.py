import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.crm import CRMActivity
from app.models.deal import Deal
from app.models.job import Job, JobStatus
from app.models.lead import Lead, ResearchReport
from app.models.outreach import SentEmail
from app.models.user import Role, User
from app.schemas.common import ok
from app.schemas.crm import (
    ActivityCreate,
    ActivityResponse,
    ContactCreate,
    ContactResponse,
    ContactUpdate,
    NoteCreate,
    NoteResponse,
    NoteUpdate,
    TimelineEvent,
)
from app.schemas.deal import DealResponse
from app.schemas.lead import AssignRequest, LeadCreate, LeadResponse, LeadUpdate
from app.services import contact_service, crm_service, lead_service

router = APIRouter()

# Roles allowed to act on leads at all (Admin/Marketing are read-only elsewhere).
_WRITERS = (Role.SALES_MANAGER, Role.SALES_EXECUTIVE)


async def _load_lead(db: AsyncSession, lead_id: uuid.UUID, user: User) -> Lead:
    """Single choke point for tenant + assigned-only isolation, used by every
    lead-scoped child route below."""

    return await lead_service.require_lead(
        db, lead_id=lead_id, company_id=user.company_id, current_user=user
    )


# --------------------------------------------------------------------------- leads


@router.get("/")
async def list_leads(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    leads = await lead_service.list_leads(db, company_id=user.company_id, current_user=user)
    return ok(data=[LeadResponse.model_validate(x) for x in leads])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_lead(
    payload: LeadCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    lead = await lead_service.create_lead(
        db, data=payload.model_dump(exclude_unset=True), current_user=user
    )
    return ok(data=LeadResponse.model_validate(lead), message="Lead created successfully")


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    lead = await _load_lead(db, lead_id, user)
    return ok(data=LeadResponse.model_validate(lead))


@router.put("/{lead_id}")
async def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    # exclude_unset, not exclude_none: the caller must be able to clear a
    # nullable field by sending it as null. exclude_none silently dropped it.
    lead = await lead_service.update_lead(
        db, lead_id=lead_id, changes=payload.model_dump(exclude_unset=True), current_user=user
    )
    return ok(data=LeadResponse.model_validate(lead), message="Lead updated")


@router.delete("/{lead_id}")
async def delete_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_MANAGER)),
):
    await lead_service.archive_lead(db, lead_id=lead_id, current_user=user)
    return ok(message="Lead archived")


@router.post("/{lead_id}/assign")
async def assign_lead(
    lead_id: uuid.UUID,
    payload: AssignRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_MANAGER)),
):
    """Gate 1 — only a Sales Manager assigns, and only to a Sales Executive in
    the same company."""

    lead = await lead_service.assign_lead(
        db, lead_id=lead_id, owner_user_id=payload.owner_user_id, current_user=user
    )
    # NOTE: also log via audit_service.log_action(category="business") once wired.
    return ok(data=LeadResponse.model_validate(lead), message="Lead assigned")


@router.post("/import-csv", status_code=status.HTTP_202_ACCEPTED)
async def import_csv(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_MANAGER, Role.ADMIN)),
):
    """Bulk import runs on Celery (can be thousands of rows) — returns a job to
    poll. File handling/dedupe lives in the worker."""

    job = Job(company_id=user.company_id, job_type="lead_import_csv", status=JobStatus.PENDING)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return ok(data={"job_id": job.id, "status": job.status}, message="Import started")


# ------------------------------------------------------------------------ contacts


@router.get("/{lead_id}/contacts")
async def list_contacts(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    contacts = await contact_service.list_for_lead(db, lead_id=lead_id, current_user=user)
    return ok(data=[ContactResponse.model_validate(c) for c in contacts])


@router.post("/{lead_id}/contacts", status_code=status.HTTP_201_CREATED)
async def create_contact(
    lead_id: uuid.UUID,
    payload: ContactCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    contact = await contact_service.create_contact(
        db, lead_id=lead_id, data=payload.model_dump(), current_user=user
    )
    return ok(data=ContactResponse.model_validate(contact), message="Contact created")


@router.put("/contacts/{contact_id}")
async def update_contact(
    contact_id: uuid.UUID,
    payload: ContactUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    # exclude_unset, not exclude_none — sending "phone": null must clear the
    # phone number, not be silently ignored.
    contact = await contact_service.update_contact(
        db, contact_id=contact_id, changes=payload.model_dump(exclude_unset=True), current_user=user
    )
    return ok(data=ContactResponse.model_validate(contact), message="Contact updated")


@router.delete("/contacts/{contact_id}")
async def delete_contact(
    contact_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    await contact_service.archive_contact(db, contact_id=contact_id, current_user=user)
    return ok(message="Contact removed")


# ---------------------------------------------------------------------- activities


@router.get("/{lead_id}/activities")
async def list_activities(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = await crm_service.list_activities(db, lead_id=lead_id, current_user=user)
    return ok(data=[ActivityResponse.model_validate(a) for a in rows])


@router.post("/{lead_id}/activities", status_code=status.HTTP_201_CREATED)
async def create_activity(
    lead_id: uuid.UUID,
    payload: ActivityCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    activity = await crm_service.create_activity(
        db, lead_id=lead_id, data=payload.model_dump(), current_user=user
    )
    return ok(data=ActivityResponse.model_validate(activity), message="Activity logged")


# There is no PUT/DELETE for activities on purpose — they are an append-only
# event log. Correcting one means logging a new event, not rewriting history.


# --------------------------------------------------------------------------- notes


@router.get("/{lead_id}/notes")
async def list_notes(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = await crm_service.list_notes(db, lead_id=lead_id, current_user=user)
    return ok(data=[NoteResponse.model_validate(n) for n in rows])


@router.post("/{lead_id}/notes", status_code=status.HTTP_201_CREATED)
async def create_note(
    lead_id: uuid.UUID,
    payload: NoteCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    note = await crm_service.create_note(
        db, lead_id=lead_id, data=payload.model_dump(), current_user=user
    )
    return ok(data=NoteResponse.model_validate(note), message="Note added")


@router.put("/notes/{note_id}")
async def update_note(
    note_id: uuid.UUID,
    payload: NoteUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    note = await crm_service.update_note(
        db, note_id=note_id, body=payload.body, current_user=user
    )
    return ok(data=NoteResponse.model_validate(note), message="Note updated")


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    await crm_service.delete_note(db, note_id=note_id, current_user=user)
    return ok(message="Note deleted")


# --------------------------------------------------------------- deals & timeline


@router.get("/{lead_id}/deals")
async def list_lead_deals(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await _load_lead(db, lead_id, user)
    rows = await db.execute(select(Deal).where(Deal.lead_id == lead_id))
    return ok(data=[DealResponse.model_validate(d) for d in rows.scalars().all()])


@router.get("/{lead_id}/timeline")
async def lead_timeline(
    lead_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Computed unified history — merges human activities, AI research, and
    sent emails into one chronological feed (the Timeline tab)."""

    await _load_lead(db, lead_id, user)
    events: list[TimelineEvent] = []

    acts = await db.execute(select(CRMActivity).where(CRMActivity.lead_id == lead_id))
    for a in acts.scalars().all():
        events.append(TimelineEvent(type=a.activity_type, timestamp=a.created_at, summary=a.description))

    reports = await db.execute(select(ResearchReport).where(ResearchReport.lead_id == lead_id))
    for r in reports.scalars().all():
        events.append(TimelineEvent(type="research_completed", timestamp=r.created_at, summary=r.summary))

    emails = await db.execute(select(SentEmail).where(SentEmail.lead_id == lead_id))
    for e in emails.scalars().all():
        events.append(TimelineEvent(type="email_sent", timestamp=e.sent_at))

    events.sort(key=lambda ev: ev.timestamp)
    return ok(data=events)
