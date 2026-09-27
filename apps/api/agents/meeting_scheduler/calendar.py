"""Slot-grid arithmetic: turn working hours minus busy time into free windows.

Kept separate from `agent.py` so the awkward part — days are local, storage is
UTC, and the two disagree — is in one place with its own tests.

The iteration runs over **local** calendar days, never UTC ones. "Tuesday" is
a fact about the tenant's timezone: for a rep in Asia/Kolkata a slot at 09:00
IST Tuesday is 03:30 UTC Tuesday, but one at 03:00 IST Tuesday is 21:30 UTC
*Monday*. Walking UTC days and labelling them would offer the customer the
wrong weekday — the one thing they explicitly asked about.

Slot boundaries are built as local wall-clock times and then converted, which
is also what makes daylight-saving transitions come out right: 10:00 local is
10:00 local on both sides of a clock change, and the UTC instant moves.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Busy:
    """A window the rep is already committed to, in UTC."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class Slot:
    start: datetime
    """UTC instant."""
    end: datetime
    tz: ZoneInfo

    @property
    def local_start(self) -> datetime:
        return self.start.astimezone(self.tz)

    @property
    def weekday(self) -> str:
        return self.local_start.strftime("%A")

    def as_dict(self) -> dict[str, Any]:
        """Rendered in the tenant's own offset (`...+05:30`), matching the
        module brief's output format. A rep reads local time; UTC on screen is
        an invitation to mis-book by hours. The UTC instants are carried
        alongside because that is what `POST /meetings` stores."""

        return {
            "start": self.local_start.isoformat(),
            "end": self.end.astimezone(self.tz).isoformat(),
            "start_utc": self.start.isoformat(),
            "end_utc": self.end.isoformat(),
            "weekday": self.weekday,
        }


def _local(day: date, at, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, at, tzinfo=tz)


def overlaps(start: datetime, end: datetime, busy: Busy, buffer: timedelta) -> bool:
    """Two windows overlap when each starts before the other ends.

    Comparisons are strict so a slot may begin exactly when a meeting ends —
    the same rule `meeting_service._check_no_clash` applies at booking time. If
    these two disagreed, the scheduler would either suggest slots that are
    rejected on save or refuse slots that would have been accepted.
    """

    return start < busy.end + buffer and end > busy.start - buffer


def generate_slots(
    *,
    now: datetime,
    config: dict[str, Any],
    duration_minutes: int,
    busy: list[Busy],
    preferred_weekdays: list[int],
) -> tuple[list[Slot], dict[str, int]]:
    """Free slots in preference order (earliest first), plus a count of what
    was rejected and why.

    The counts are not diagnostics for us — they are the answer to "why is this
    list empty", which is the most common real outcome once a customer names a
    single day. `campaign_service.select_audience` reports `limiting_criterion`
    for the same reason: a bare zero is unactionable.
    """

    tz: ZoneInfo = config["tz"]
    duration = timedelta(minutes=duration_minutes)
    interval = timedelta(minutes=config["slot_interval_minutes"])
    spread = timedelta(minutes=config["slot_spread_minutes"])
    buffer = timedelta(minutes=config["buffer_minutes"])
    earliest = now + timedelta(minutes=config["min_notice_minutes"])

    slots: list[Slot] = []
    eliminated = {"non_working_day": 0, "not_preferred_day": 0, "too_soon": 0, "busy": 0}

    local_today = now.astimezone(tz).date()
    for offset in range(config["search_horizon_days"]):
        if len(slots) >= config["max_slots"]:
            break
        day = local_today + timedelta(days=offset)

        # Preference is filtered *before* the working-day check on purpose, so
        # `non_working_day` only ever counts days the customer actually asked
        # for. Checked the other way round, requesting Sunday would count every
        # weekend in the horizon as non-working even though nobody wanted those
        # days, muddying the reason reported back.
        if preferred_weekdays and day.weekday() not in preferred_weekdays:
            # Counted, never overridden. Offering Thursday to a customer who
            # asked for Tuesday reads as the agent ignoring them; reporting
            # zero and naming the constraint lets the rep decide.
            eliminated["not_preferred_day"] += 1
            continue
        if day.weekday() not in config["working_days"]:
            eliminated["non_working_day"] += 1
            continue

        day_end = _local(day, config["work_end"], tz)
        cursor = _local(day, config["work_start"], tz)
        taken_today = 0

        while cursor + duration <= day_end:
            start = cursor.astimezone(UTC)
            end = (cursor + duration).astimezone(UTC)

            if start < earliest:
                eliminated["too_soon"] += 1
            elif any(overlaps(start, end, block, buffer) for block in busy):
                eliminated["busy"] += 1
            else:
                slots.append(Slot(start=start, end=end, tz=tz))
                taken_today += 1
                if taken_today >= config["max_slots_per_day"] or len(slots) >= config["max_slots"]:
                    break
                # Skip ahead so the next suggestion on this day is a genuine
                # alternative rather than the adjacent half hour.
                cursor += max(spread, interval)
                continue

            cursor += interval

    return slots, eliminated


def free_windows(
    *, start: datetime, end: datetime, busy: list[Busy], buffer: timedelta
) -> list[tuple[datetime, datetime]]:
    """Subtract busy time from one window, returning what is left.

    Used by `/meetings/availability`, which shows a day rather than proposing
    slots — so no notice period or grid is applied here. Overlapping meetings
    are merged first; without that, two meetings that overlap each other would
    each carve out their own gap and produce a "free" window between them that
    is not free.
    """

    blocks = sorted(
        ((b.start - buffer, b.end + buffer) for b in busy if b.end > start and b.start < end),
    )
    merged: list[list[datetime]] = []
    for block_start, block_end in blocks:
        if merged and block_start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], block_end)
        else:
            merged.append([block_start, block_end])

    free: list[tuple[datetime, datetime]] = []
    cursor = start
    for block_start, block_end in merged:
        if block_start > cursor:
            free.append((cursor, min(block_start, end)))
        cursor = max(cursor, block_end)
        if cursor >= end:
            break
    if cursor < end:
        free.append((cursor, end))
    return [(s, e) for s, e in free if e > s]


# Most specific reason first. **Deliberately not ranked by count**, which is
# the obvious implementation and is wrong here: `not_preferred_day` counts
# every day the customer didn't ask for, so it out-numbers every real blocker.
# A customer who asks for Tuesday and finds every Tuesday booked would be told
# "widen preferred_days" — advice to abandon their own request — instead of
# "those hours are taken".
CONSTRAINT_PRIORITY: tuple[str, ...] = (
    "busy",
    "too_soon",
    "non_working_day",
    "not_preferred_day",
)


def limiting_constraint(eliminated: dict[str, int]) -> str | None:
    """Which rule to relax first when nothing came back."""

    for reason in CONSTRAINT_PRIORITY:
        if eliminated.get(reason):
            return reason
    return None
