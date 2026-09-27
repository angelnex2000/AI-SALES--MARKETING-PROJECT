"""Scheduling policy — working hours, notice period, and how slots are spread.

**Working hours belong to the tenant, and are meaningless without a
timezone.** The module brief says "working hours: 10 AM – 6 PM" and shows
output at `+05:30`, but every datetime in this system is stored in UTC. Treat
"10:00" as UTC and an Indian rep is offered meetings from 15:30 to 23:30 local
— a scheduler that is confidently, silently wrong for everyone outside one
timezone. So hours are evaluated in a named zone and converted, never assumed.

`Company.scheduling_config` holds it, for the same reason `icp_config` holds
the ICP: a German logistics vendor and an Indian health-tech startup do not
share a working day, a weekend, or a notion of "reasonable notice".

The default timezone is **UTC rather than a guess**. An unconfigured workspace
gets slots that are explicable (and visibly labelled UTC) instead of slots
computed against someone else's country.
"""

from datetime import time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Python's `date.weekday()`: Monday is 0, Sunday is 6.
WEEKDAY_NAMES: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Accepted spellings for `preferred_days`. A customer writes "Tues", a UI sends
# "Tuesday"; both must resolve, and anything else must be rejected rather than
# quietly ignored — silently dropping the one day the customer asked for and
# offering Thursday instead is worse than an error.
_DAY_ALIASES: dict[str, int] = {
    **{name: index for index, name in enumerate(WEEKDAY_NAMES)},
    **{name[:3]: index for index, name in enumerate(WEEKDAY_NAMES)},
    "tues": 1,
    "thur": 3,
    "thurs": 3,
}

DEFAULT_SCHEDULING: dict[str, Any] = {
    "timezone": "UTC",
    "working_days": [0, 1, 2, 3, 4],
    "work_start": "10:00",
    "work_end": "18:00",
    "default_duration_minutes": 30,
    # Grid resolution. Slots start on the half hour, not at arbitrary minutes.
    "slot_interval_minutes": 30,
    # Nothing is offered sooner than this. "Prefer the earliest slot" taken
    # literally proposes a demo 15 minutes from now: no time to prepare, and no
    # time for the customer to see the invite before it starts.
    "min_notice_minutes": 120,
    "search_horizon_days": 14,
    "max_slots": 5,
    "max_slots_per_day": 2,
    # Distance between two suggestions on the same day. Offering 10:00 and
    # 10:30 is not a choice — it is the same slot twice. The brief's own worked
    # example spreads across the day (11:00 and 15:30).
    "slot_spread_minutes": 120,
    # Gap required either side of an existing meeting. Zero by default so a
    # suggestion is never rejected by `meeting_service._check_no_clash`, which
    # allows back-to-back bookings; raise it per tenant for travel or prep.
    "buffer_minutes": 0,
}


class SchedulingConfigError(ValueError):
    """The tenant's scheduling config cannot produce slots.

    Raised rather than silently falling back: a typo in a timezone name would
    otherwise move every suggested meeting by hours with nothing to show for
    it, and an admin who can see the error can fix it.
    """


def _parse_time(value: Any, field: str) -> time:
    try:
        hour, _, minute = str(value).partition(":")
        return time(int(hour), int(minute or 0))
    except (TypeError, ValueError) as exc:
        raise SchedulingConfigError(f"{field} must be HH:MM, got {value!r}") from exc


def parse_weekdays(names: list[str] | None) -> list[int]:
    """Map day names to `date.weekday()` indices, rejecting anything unknown."""

    if not names:
        return []
    resolved: list[int] = []
    for name in names:
        index = _DAY_ALIASES.get(str(name).strip().lower())
        if index is None:
            raise SchedulingConfigError(
                f"Unrecognised day {name!r} — expected one of {', '.join(WEEKDAY_NAMES)}"
            )
        if index not in resolved:
            resolved.append(index)
    return resolved


def resolve_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Shallow-merge a tenant's stored config over the defaults and validate it.

    Shallow like `icp_matching.resolve_profile`: a tenant that only set a
    timezone still gets default hours. Validation happens here rather than at
    the column so a bad value fails at the point it would produce wrong times,
    with a message naming the field.
    """

    merged = {**DEFAULT_SCHEDULING, **(config or {})}

    try:
        tz = ZoneInfo(str(merged["timezone"]))
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise SchedulingConfigError(
            f"Unknown timezone {merged['timezone']!r} — use an IANA name like 'Asia/Kolkata'"
        ) from exc

    work_start = _parse_time(merged["work_start"], "work_start")
    work_end = _parse_time(merged["work_end"], "work_end")
    if work_end <= work_start:
        raise SchedulingConfigError(
            f"work_end ({merged['work_end']}) must be after work_start ({merged['work_start']})"
        )

    working_days = [int(d) for d in merged["working_days"]]
    if not working_days:
        raise SchedulingConfigError("working_days is empty — no day would ever be schedulable")
    if any(d < 0 or d > 6 for d in working_days):
        raise SchedulingConfigError("working_days must be 0 (Monday) through 6 (Sunday)")

    for field in (
        "slot_interval_minutes",
        "search_horizon_days",
        "max_slots",
        "max_slots_per_day",
    ):
        if int(merged[field]) < 1:
            raise SchedulingConfigError(f"{field} must be at least 1")

    merged.update(
        {
            "tz": tz,
            "timezone": str(merged["timezone"]),
            "work_start": work_start,
            "work_end": work_end,
            "working_days": working_days,
            "slot_interval_minutes": int(merged["slot_interval_minutes"]),
            "min_notice_minutes": max(0, int(merged["min_notice_minutes"])),
            "search_horizon_days": int(merged["search_horizon_days"]),
            "max_slots": int(merged["max_slots"]),
            "max_slots_per_day": int(merged["max_slots_per_day"]),
            "slot_spread_minutes": max(0, int(merged["slot_spread_minutes"])),
            "buffer_minutes": max(0, int(merged["buffer_minutes"])),
        }
    )
    return merged


# Duration bounds, checked against the request rather than the config. A
# non-positive duration produces an infinite slot grid; a multi-day one
# produces none, silently.
MIN_DURATION_MINUTES = 5
MAX_DURATION_MINUTES = 480


def validate_duration(minutes: Any) -> int:
    try:
        value = int(minutes)
    except (TypeError, ValueError) as exc:
        raise SchedulingConfigError(f"duration_minutes must be a number, got {minutes!r}") from exc
    if not MIN_DURATION_MINUTES <= value <= MAX_DURATION_MINUTES:
        raise SchedulingConfigError(
            f"duration_minutes must be between {MIN_DURATION_MINUTES} and {MAX_DURATION_MINUTES}"
        )
    return value
