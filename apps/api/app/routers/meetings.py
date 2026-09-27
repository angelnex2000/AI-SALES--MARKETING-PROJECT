"""Module 7 — Meetings.

Booking is the assigned Sales Exec only. Manager/Admin read; Marketing has no
access at all. The Scheduler is the one rule-based agent (via the orchestrator).
Recording an outcome is a business event that updates the CRM in one call.
"""

import uuid
from datetime import UTC, datetime
from datetime import date as _date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.dependencies.auth import require_role
from app.dependencies.db import get_db
from app.models.job import Job, JobStatus
from app.models.meeting import MeetingStatus, MeetingType
from app.models.user import Role, User
from app.schemas.common import ok
from app.services import meeting_service

router = APIRouter()

# Marketing is excluded entirely; Admin/Manager read; Sales Exec writes.
_READERS = (Role.ADMIN, Role.SALES_MANAGER, Role.SALES_EXECUTIVE)


def _utc(v: datetime) -> datetime:
    """Normalise every inbound timestamp to timezone-aware UTC, so a client
    that omits an offset cannot store a naive value whose meaning depends on
    the server's timezone."""

    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


class MeetingCreate(BaseModel):
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    title: str = Field(default="Meeting", min_length=1, max_length=255)
    meeting_type: MeetingType = MeetingType.DEMO
    scheduled_at: datetime
    ends_at: datetime
    location: str | None = None
    notes: str | None = None

    @field_validator("scheduled_at", "ends_at")
    @classmethod
    def _normalise(cls, v: datetime) -> datetime:
        return _utc(v)


class MeetingUpdate(BaseModel):
    """Separate from MeetingCreate: reusing the create model forced callers to
    resend lead_id (which is not editable) and silently blanked `notes`
    whenever it was omitted. Dumped with exclude_unset so omitted fields are
    left alone."""

    contact_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    meeting_type: MeetingType | None = None
    scheduled_at: datetime | None = None
    ends_at: datetime | None = None
    location: str | None = None
    notes: str | None = None

    @field_validator("title", "meeting_type", "scheduled_at", "ends_at")
    @classmethod
    def _not_cleared(cls, v, info):
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return _utc(v) if isinstance(v, datetime) else v


class MeetingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None
    owner_id: uuid.UUID
    title: str
    meeting_type: MeetingType
    scheduled_at: datetime
    ends_at: datetime
    location: str | None
    status: MeetingStatus
    notes: str | None
    outcome: str | None
    next_action: str | None


class SuggestSlotsRequest(BaseModel):
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    duration_minutes: int | None = None
    """Null falls back to the tenant's configured default rather than a
    hardcoded 30 — the length of a demo is a per-tenant fact."""
    preferred_days: list[str] = []
    """Day names the customer asked for, e.g. ["Tuesday"]. Honoured strictly:
    an empty result is returned with the reason rather than quietly widening to
    a day nobody requested."""


class OutcomeRequest(BaseModel):
    outcome: str
    notes: str | None = None
    next_action: str | None = None


@router.get("/")
async def list_meetings(
    lead_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_READERS)),
):
    meetings = await meeting_service.list_meetings(db, user=user, lead_id=lead_id)
    return ok(data=[MeetingResponse.model_validate(m) for m in meetings])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    meeting = await meeting_service.create_meeting(db, data=payload.model_dump(), user=user)
    return ok(data=MeetingResponse.model_validate(meeting), message="Meeting scheduled")


@router.get("/availability")
async def availability(
    date: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Busy and free time on one date, for the calling rep, in the tenant's
    timezone.

    `availability_sources` reports where the picture came from. It is
    `["internal"]` until the calendar integration lands: a Google standup is
    invisible to us, so this must not be read as "the rep is definitely free".
    """

    try:
        day = _date.fromisoformat(date)
    except ValueError as exc:
        raise ValidationError(
            "date must be YYYY-MM-DD", error_code="INVALID_DATE"
        ) from exc
    return ok(data=await meeting_service.day_availability(db, user=user, day=day))


@router.post("/suggest-slots")
async def suggest_slots(
    payload: SuggestSlotsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Meeting Scheduler agent (rule-based), via `meeting_service`.

    Returns proposals only — 200, not 202: this is arithmetic over the rep's
    calendar, so there is no slow model to wait on and no Job to poll.
    Creating the meeting stays a separate, human-initiated `POST /meetings`,
    which re-checks for clashes before it writes.
    """

    data = await meeting_service.suggest_slots(
        db,
        user=user,
        lead_id=payload.lead_id,
        contact_id=payload.contact_id,
        duration_minutes=payload.duration_minutes,
        preferred_days=payload.preferred_days,
    )
    message = (
        "Slots suggested"
        if data["suggested_slots"]
        else "No slots available — see limiting_constraint"
    )
    return ok(data=data, message=message)


@router.get("/{meeting_id}")
async def get_meeting(
    meeting_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(require_role(*_READERS))
):
    meeting = await meeting_service.require_meeting(db, meeting_id=meeting_id, user=user)
    return ok(data=MeetingResponse.model_validate(meeting))


@router.put("/{meeting_id}")
async def update_meeting(
    meeting_id: uuid.UUID,
    payload: MeetingUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    meeting = await meeting_service.update_meeting(
        db, meeting_id=meeting_id, changes=payload.model_dump(exclude_unset=True), user=user
    )
    return ok(data=MeetingResponse.model_validate(meeting), message="Meeting updated")


@router.delete("/{meeting_id}")
async def cancel_meeting(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    await meeting_service.cancel_meeting(db, meeting_id=meeting_id, user=user)
    return ok(message="Meeting cancelled")


@router.post("/{meeting_id}/outcome")
async def record_outcome(
    meeting_id: uuid.UUID,
    payload: OutcomeRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Business event: mark the meeting complete, log a timeline activity, and
    enqueue a forecast refresh (deal-stage advance is a follow-up human step)."""

    meeting = await meeting_service.record_outcome(
        db,
        meeting_id=meeting_id,
        outcome=payload.outcome,
        notes=payload.notes,
        next_action=payload.next_action,
        user=user,
    )
    return ok(data=MeetingResponse.model_validate(meeting), message="Outcome recorded")


@router.post("/{meeting_id}/sync-calendar", status_code=status.HTTP_202_ACCEPTED)
async def sync_calendar(
    meeting_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Push to Google/Outlook via the Integration service (retry-friendly)."""

    meeting = await meeting_service.require_meeting(db, meeting_id=meeting_id, user=user)
    job = Job(
        company_id=user.company_id, job_type="calendar_sync", lead_id=meeting.lead_id, status=JobStatus.PENDING
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return ok(data={"job_id": job.id, "status": job.status}, message="Calendar sync started")
