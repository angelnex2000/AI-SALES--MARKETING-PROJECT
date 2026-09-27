"""Meeting Scheduler Agent — Phase 8 Module 11.

Turns "can we do a demo next Tuesday?" into concrete slots a rep can offer.

Rule-based, and staying that way: working hours minus existing meetings has
exactly one right answer, so routing it through a model would add latency,
cost and run-to-run variance to arithmetic. Same call as the Campaign Agent's
strategy lookup.

Three things this agent does not do:

  * **Book anything.** It returns suggestions; `POST /meetings` creates the
    meeting after a Sales Executive picks one, and that path re-checks for
    clashes. The brief's own flow puts the human between the two, and it has
    to stay there: these slots are computed from a snapshot of the rep's
    calendar, so by the time the customer accepts, the rep may have booked
    something else. The suggestion is advisory; `_check_no_clash` at save time
    is the authority — exactly the relationship between
    `AudienceSegment.selected_lead_ids` and the audience query.
  * **Touch the database.** Busy windows arrive in the payload, gathered by
    `meeting_service.suggest_slots`, so the agent stays runnable from a mock.
  * **Quietly widen a constraint.** If the customer said Tuesday and Tuesday
    is full, the answer is an empty list plus the reason — not Thursday.
"""

from datetime import UTC, datetime
from typing import Any

from agents.base import BaseAgent
from agents.meeting_scheduler import calendar as slot_calendar
from agents.meeting_scheduler.rules import (
    SchedulingConfigError,
    parse_weekdays,
    resolve_config,
    validate_duration,
)

MODEL_NAME = "meeting_scheduler"
MODEL_VERSION = "meeting-scheduler-rules-v1"

# Wording for `limiting_constraint`, phrased as the thing to change rather
# than the thing that failed. "0 slots" on its own tells a rep nothing.
CONSTRAINT_ADVICE: dict[str, str] = {
    "not_preferred_day": (
        "every candidate fell outside the requested day(s) — widen preferred_days"
    ),
    "busy": "the working hours in range are already booked — try a later date or a shorter meeting",
    "too_soon": (
        "the only free times are inside the notice period — look further ahead or reduce "
        "min_notice_minutes"
    ),
    "non_working_day": "the range covers only non-working days — extend search_horizon_days",
}


class MeetingSchedulerAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        config = resolve_config(input_data.get("scheduling_config"))
        # `is None`, not `or`: an explicit `duration_minutes: 0` is a caller
        # error and must be rejected, but `or` treats it as "unspecified" and
        # silently books a 30-minute meeting instead.
        requested = input_data.get("duration_minutes")
        duration = validate_duration(
            config["default_duration_minutes"] if requested is None else requested
        )
        preferred = parse_weekdays(input_data.get("preferred_days"))

        # Injectable so the agent is deterministic under test. Everything
        # downstream is arithmetic on this instant.
        now = self._as_utc(input_data.get("now")) or datetime.now(UTC)
        busy = self._busy_windows(input_data.get("busy") or [])

        slots, eliminated = slot_calendar.generate_slots(
            now=now,
            config=config,
            duration_minutes=duration,
            busy=busy,
            preferred_weekdays=preferred,
        )
        constraint = slot_calendar.limiting_constraint(eliminated) if not slots else None

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "timezone": config["timezone"],
            "duration_minutes": duration,
            "suggested_slots": [slot.as_dict() for slot in slots],
            # "Prefer the earliest available slot" — the list is already in
            # preference order, so the recommendation is its head.
            "recommended_slot": slots[0].as_dict() if slots else None,
            "eliminated": eliminated,
            "limiting_constraint": constraint,
            "explanation": self._explain(slots, config, duration, preferred, constraint),
            # Local meetings only. Stated in the payload rather than implied,
            # because "free" here means "nothing booked in *this* system" —
            # see meeting_service.suggest_slots.
            "availability_sources": ["internal"],
        }

    # ----------------------------------------------------------------- inputs

    def _as_utc(self, value: Any) -> datetime | None:
        if value is None:
            return None
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)

    def _busy_windows(self, raw: list[Any]) -> list[slot_calendar.Busy]:
        windows: list[slot_calendar.Busy] = []
        for entry in raw:
            start = self._as_utc(entry["start"] if isinstance(entry, dict) else entry[0])
            end = self._as_utc(entry["end"] if isinstance(entry, dict) else entry[1])
            if start is None or end is None or end <= start:
                # A zero-length or inverted window blocks nothing; skipping it
                # is safe, whereas letting it through makes `overlaps` behave
                # unpredictably around the boundary.
                continue
            windows.append(slot_calendar.Busy(start=start, end=end))
        return windows

    # ------------------------------------------------------------ explanation

    def _explain(
        self,
        slots: list[slot_calendar.Slot],
        config: dict[str, Any],
        duration: int,
        preferred: list[int],
        constraint: str | None,
    ) -> str:
        hours = (
            f"{config['work_start'].strftime('%H:%M')}–"
            f"{config['work_end'].strftime('%H:%M')} {config['timezone']}"
        )
        if not slots:
            advice = CONSTRAINT_ADVICE.get(constraint or "", "no candidate windows were generated")
            return (
                f"No free {duration}-minute slot within {config['search_horizon_days']} days "
                f"during working hours ({hours}): {advice}."
            )

        days = sorted({slot.weekday for slot in slots})
        detail = (
            f"Found {len(slots)} free {duration}-minute slot(s) on {', '.join(days)} "
            f"within working hours ({hours}), skipping times inside the "
            f"{config['min_notice_minutes']}-minute notice window and any already booked. "
            f"Recommending the earliest: {slots[0].local_start.strftime('%a %d %b %H:%M')}."
        )
        if preferred:
            detail += " Restricted to the day(s) the customer asked for."
        return detail


__all__ = ["MODEL_NAME", "MODEL_VERSION", "MeetingSchedulerAgent", "SchedulingConfigError"]
