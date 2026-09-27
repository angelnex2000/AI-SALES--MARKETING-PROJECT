"""Meeting scheduling.

A meeting is a sales milestone, so booking one is a business event: it must
land on the lead's timeline, it must not silently collide with another
booking, and its outcome may only be recorded once.

Visibility follows the parent lead, like deals and drafts — a Sales Executive
sees only meetings for leads assigned to them.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.meeting_scheduler import calendar as slot_calendar
from agents.meeting_scheduler.agent import MeetingSchedulerAgent
from agents.meeting_scheduler.rules import SchedulingConfigError, resolve_config
from app.core.exceptions import NotFoundError, ValidationError
from app.models.company import Company
from app.models.lead import Contact, Lead
from app.models.meeting import Meeting, MeetingStatus
from app.models.user import Role, User
from app.services import crm_service, lead_service

# A cancelled meeting no longer occupies its slot, so it is excluded from
# clash detection.
BLOCKING_STATUSES = (MeetingStatus.SCHEDULED, MeetingStatus.COMPLETED)


def _visible(stmt: Select, *, user: User) -> Select:
    stmt = stmt.join(Lead, Meeting.lead_id == Lead.id).where(
        Meeting.company_id == user.company_id,
        Lead.archived_at.is_(None),
    )
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == user.id)
    return stmt


async def list_meetings(
    db: AsyncSession, *, user: User, lead_id: uuid.UUID | None = None
) -> list[Meeting]:
    stmt = _visible(select(Meeting), user=user)
    if lead_id is not None:
        stmt = stmt.where(Meeting.lead_id == lead_id)
    return list((await db.execute(stmt.order_by(Meeting.scheduled_at))).scalars().all())


async def require_meeting(db: AsyncSession, *, meeting_id: uuid.UUID, user: User) -> Meeting:
    stmt = _visible(select(Meeting).where(Meeting.id == meeting_id), user=user)
    meeting = (await db.execute(stmt)).scalar_one_or_none()
    if meeting is None:
        raise NotFoundError("Meeting not found", error_code="MEETING_NOT_FOUND")
    return meeting


def _as_utc(dt: datetime) -> datetime:
    """Coerce to timezone-aware UTC before any comparison.

    Incoming payloads carry an offset, but values read back from the database
    may be naive depending on the driver — SQLite has no timezone type, so it
    returns naive datetimes even for a `DateTime(timezone=True)` column.
    Comparing the two raises `TypeError: can't compare offset-naive and
    offset-aware datetimes`, which surfaces as a 500 on an ordinary reschedule.
    """

    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _check_window(scheduled_at: datetime, ends_at: datetime) -> None:
    if _as_utc(ends_at) <= _as_utc(scheduled_at):
        raise ValidationError("Meeting must end after it starts", error_code="INVALID_TIME_WINDOW")


async def _check_contact(
    db: AsyncSession, *, contact_id: uuid.UUID | None, lead_id: uuid.UUID, company_id: uuid.UUID
) -> None:
    """The attendee must be a contact at this lead — booking a demo against
    someone from an unrelated account is always a mistake."""

    if contact_id is None:
        return
    stmt = select(Contact).where(
        Contact.id == contact_id,
        Contact.company_id == company_id,
        Contact.lead_id == lead_id,
        Contact.archived_at.is_(None),
    )
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise ValidationError(
            "contact_id does not belong to this lead", error_code="CONTACT_LEAD_MISMATCH"
        )


async def _check_no_clash(
    db: AsyncSession,
    *,
    owner_id: uuid.UUID,
    company_id: uuid.UUID,
    scheduled_at: datetime,
    ends_at: datetime,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Reject a booking that overlaps one the same rep already holds.

    Two windows overlap when each starts before the other ends. Touching
    endpoints (one ends exactly when the next begins) are fine, which is why
    the comparisons are strict.
    """

    stmt = select(Meeting).where(
        Meeting.company_id == company_id,
        Meeting.owner_id == owner_id,
        Meeting.status.in_(BLOCKING_STATUSES),
        Meeting.scheduled_at < ends_at,
        Meeting.ends_at > scheduled_at,
    )
    if exclude_id is not None:
        stmt = stmt.where(Meeting.id != exclude_id)
    clash = (await db.execute(stmt)).scalars().first()
    if clash is not None:
        raise ValidationError(
            f"Overlaps an existing meeting at {clash.scheduled_at.isoformat()}",
            error_code="MEETING_CONFLICT",
            details={"conflicting_meeting_id": str(clash.id)},
        )


# --------------------------------------------------------------- scheduling

# Note on what "free" means here: busy time is read from **this system's**
# meetings only. The calendar integration (`Integration` / `sync-calendar`) is
# still a stub, so a rep's Google standup is invisible to us. Every response
# carries `availability_sources: ["internal"]` rather than implying we checked
# their real calendar — a slot presented as free that collides with a standup
# is a booking the rep has to unwind with the customer.


async def _scheduling_config(db: AsyncSession, company_id: uuid.UUID) -> dict | None:
    company = await db.get(Company, company_id)
    return company.scheduling_config if company else None


def _resolved(config: dict | None) -> dict:
    """Resolve the tenant's config, turning a bad value into a 422 naming the
    field rather than a 500 out of slot arithmetic."""

    try:
        return resolve_config(config)
    except SchedulingConfigError as exc:
        raise ValidationError(str(exc), error_code="INVALID_SCHEDULING_CONFIG") from exc


async def _busy_windows(
    db: AsyncSession, *, owner_id: uuid.UUID, company_id: uuid.UUID, start: datetime, end: datetime
) -> list[slot_calendar.Busy]:
    """Meetings the rep already holds that intersect the search range.

    Scoped to `owner_id`, not the tenant: a slot is unavailable because *this*
    rep is busy. `BLOCKING_STATUSES` is reused so a cancelled meeting frees its
    slot here exactly as it does in `_check_no_clash` — if the two disagreed,
    the scheduler would offer slots that are rejected on save.
    """

    stmt = select(Meeting).where(
        Meeting.company_id == company_id,
        Meeting.owner_id == owner_id,
        Meeting.status.in_(BLOCKING_STATUSES),
        Meeting.scheduled_at < end,
        Meeting.ends_at > start,
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [
        slot_calendar.Busy(start=_as_utc(m.scheduled_at), end=_as_utc(m.ends_at)) for m in rows
    ]


async def suggest_slots(
    db: AsyncSession,
    *,
    user: User,
    lead_id: uuid.UUID,
    contact_id: uuid.UUID | None = None,
    duration_minutes: int | None = None,
    preferred_days: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    """Module 11 — propose times, and nothing more.

    Slots are computed for **the calling Sales Executive**, who is also who
    `create_meeting` books for (`owner_id=user.id`). The brief's payload has an
    `owner_user_id`; honouring it would mean offering slots read from rep A's
    calendar to a caller whose booking is checked against rep B's, so every
    suggestion could fail `_check_no_clash` on save.

    Nothing is created. The returned slots are a snapshot: the rep may book
    something else before the customer accepts, which is why the real guard is
    the clash check at booking time, not this list.
    """

    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=user.company_id, current_user=user
    )
    await _check_contact(db, contact_id=contact_id, lead_id=lead_id, company_id=user.company_id)

    stored = await _scheduling_config(db, user.company_id)
    config = _resolved(stored)
    moment = _as_utc(now) if now else datetime.now(UTC)

    busy = await _busy_windows(
        db,
        owner_id=user.id,
        company_id=user.company_id,
        start=moment,
        end=moment + timedelta(days=config["search_horizon_days"] + 1),
    )

    try:
        return await MeetingSchedulerAgent().run(
            {
                "lead_id": str(lead_id),
                "contact_id": str(contact_id) if contact_id else None,
                "owner_user_id": str(user.id),
                "scheduling_config": stored,
                "duration_minutes": duration_minutes,
                "preferred_days": preferred_days,
                "busy": [{"start": b.start, "end": b.end} for b in busy],
                "now": moment,
            }
        )
    except SchedulingConfigError as exc:
        # Covers the request-supplied values too — an unrecognised day name or
        # an out-of-range duration is the caller's error, not a server fault.
        raise ValidationError(str(exc), error_code="INVALID_SCHEDULING_REQUEST") from exc


async def day_availability(db: AsyncSession, *, user: User, day: date) -> dict:
    """Busy and free time for one working day, for the calling rep.

    Unlike `suggest_slots` this applies no notice period and no grid — it
    answers "what does that day look like", so a rep can see a gap the
    scheduler declined to offer because it was too soon.
    """

    config = _resolved(await _scheduling_config(db, user.company_id))
    tz = config["tz"]
    window_start = datetime.combine(day, config["work_start"], tzinfo=tz).astimezone(UTC)
    window_end = datetime.combine(day, config["work_end"], tzinfo=tz).astimezone(UTC)

    busy = await _busy_windows(
        db,
        owner_id=user.id,
        company_id=user.company_id,
        start=window_start,
        end=window_end,
    )
    free = slot_calendar.free_windows(
        start=window_start,
        end=window_end,
        busy=busy,
        buffer=timedelta(minutes=config["buffer_minutes"]),
    )

    def _pair(start: datetime, end: datetime) -> dict:
        return {"start": start.astimezone(tz).isoformat(), "end": end.astimezone(tz).isoformat()}

    return {
        "date": day.isoformat(),
        "timezone": config["timezone"],
        "is_working_day": day.weekday() in config["working_days"],
        "working_hours": _pair(window_start, window_end),
        "busy": [_pair(b.start, b.end) for b in sorted(busy, key=lambda b: b.start)],
        "free": [_pair(start, end) for start, end in free],
        "availability_sources": ["internal"],
    }


async def create_meeting(db: AsyncSession, *, data: dict, user: User) -> Meeting:
    lead_id = data["lead_id"]
    await lead_service.require_lead(
        db, lead_id=lead_id, company_id=user.company_id, current_user=user
    )
    _check_window(data["scheduled_at"], data["ends_at"])
    await _check_contact(
        db, contact_id=data.get("contact_id"), lead_id=lead_id, company_id=user.company_id
    )
    await _check_no_clash(
        db,
        owner_id=user.id,
        company_id=user.company_id,
        scheduled_at=data["scheduled_at"],
        ends_at=data["ends_at"],
    )

    meeting = Meeting(
        company_id=user.company_id,
        owner_id=user.id,  # an exec books on their own behalf
        **data,
    )
    db.add(meeting)
    # Module 14 step 4 — booking is a milestone, so it belongs on the timeline.
    await crm_service.log_system_activity(
        db,
        company_id=user.company_id,
        lead_id=lead_id,
        actor_id=user.id,
        activity_type="meeting_scheduled",
        description=f"{meeting.meeting_type.value} scheduled for {meeting.scheduled_at.isoformat()}",
    )
    await db.commit()
    await db.refresh(meeting)
    return meeting


async def update_meeting(
    db: AsyncSession, *, meeting_id: uuid.UUID, changes: dict, user: User
) -> Meeting:
    meeting = await require_meeting(db, meeting_id=meeting_id, user=user)
    if meeting.status in (MeetingStatus.COMPLETED, MeetingStatus.CANCELLED):
        raise ValidationError(
            f"A {meeting.status.value} meeting cannot be rescheduled",
            error_code="MEETING_NOT_EDITABLE",
        )

    scheduled_at = changes.get("scheduled_at", meeting.scheduled_at)
    ends_at = changes.get("ends_at", meeting.ends_at)
    _check_window(scheduled_at, ends_at)
    if "contact_id" in changes:
        await _check_contact(
            db,
            contact_id=changes["contact_id"],
            lead_id=meeting.lead_id,
            company_id=user.company_id,
        )
    if "scheduled_at" in changes or "ends_at" in changes:
        await _check_no_clash(
            db,
            owner_id=meeting.owner_id,
            company_id=user.company_id,
            scheduled_at=scheduled_at,
            ends_at=ends_at,
            exclude_id=meeting.id,
        )

    for field, value in changes.items():
        setattr(meeting, field, value)
    await db.commit()
    await db.refresh(meeting)
    return meeting


async def cancel_meeting(db: AsyncSession, *, meeting_id: uuid.UUID, user: User) -> None:
    meeting = await require_meeting(db, meeting_id=meeting_id, user=user)
    if meeting.status == MeetingStatus.COMPLETED:
        raise ValidationError(
            "A completed meeting cannot be cancelled", error_code="MEETING_ALREADY_COMPLETED"
        )
    meeting.status = MeetingStatus.CANCELLED
    await crm_service.log_system_activity(
        db,
        company_id=user.company_id,
        lead_id=meeting.lead_id,
        actor_id=user.id,
        activity_type="meeting_cancelled",
        description=f"Meeting on {meeting.scheduled_at.isoformat()} cancelled",
    )
    await db.commit()


async def record_outcome(
    db: AsyncSession,
    *,
    meeting_id: uuid.UUID,
    outcome: str,
    notes: str | None,
    next_action: str | None,
    user: User,
) -> Meeting:
    """Business event: complete the meeting, put it on the timeline, and
    refresh the forecast. Recording twice is rejected — it would duplicate the
    activity and enqueue a second forecast run."""

    from app.services import job_service

    meeting = await require_meeting(db, meeting_id=meeting_id, user=user)
    if meeting.outcome is not None:
        raise ValidationError(
            "An outcome has already been recorded for this meeting",
            error_code="OUTCOME_ALREADY_RECORDED",
        )
    if meeting.status == MeetingStatus.CANCELLED:
        raise ValidationError("A cancelled meeting has no outcome", error_code="MEETING_CANCELLED")

    meeting.status = MeetingStatus.COMPLETED
    meeting.outcome = outcome
    meeting.next_action = next_action
    if notes is not None:
        meeting.notes = notes

    await crm_service.log_system_activity(
        db,
        company_id=user.company_id,
        lead_id=meeting.lead_id,
        actor_id=user.id,
        activity_type="meeting_outcome",
        description=f"{outcome}. Next: {next_action or 'n/a'}",
    )
    # Deal-stage advance stays a deliberate human step (PATCH /deals/{id}/stage);
    # the forecast is refreshed because a completed meeting shifts win odds.
    await job_service.get_or_create(
        db, user=user, job_type="revenue_forecast", lead_id=meeting.lead_id
    )
    await db.commit()
    await db.refresh(meeting)
    return meeting
