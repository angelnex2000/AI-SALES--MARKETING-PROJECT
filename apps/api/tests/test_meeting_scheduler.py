"""Meeting Scheduler Agent — timezone correctness, constraints, and the
promise that a suggested slot is actually bookable.

The rule under test throughout: "working hours 10-6" is not a fact until you
say *where*. Every datetime in this system is UTC, so the interesting failures
are all conversions.
"""

from datetime import UTC, datetime, timedelta

import pytest

from agents.meeting_scheduler.agent import MODEL_VERSION, MeetingSchedulerAgent
from agents.meeting_scheduler.calendar import Busy, free_windows
from agents.meeting_scheduler.rules import (
    DEFAULT_SCHEDULING,
    SchedulingConfigError,
    parse_weekdays,
    resolve_config,
    validate_duration,
)

V1 = "/api/v1"

IST = {"timezone": "Asia/Kolkata"}
NY = {"timezone": "America/New_York"}

# Monday 2026-07-06, 03:00 UTC = 08:30 IST — before the working day starts.
MONDAY_MORNING = datetime(2026, 7, 6, 3, 0, tzinfo=UTC)


async def suggest(**kwargs) -> dict:
    payload = {"now": MONDAY_MORNING, **kwargs}
    return await MeetingSchedulerAgent().run(payload)


class TestTimezone:
    """The failure the brief's "10 AM - 6 PM" hides.

    Storage is UTC. Treat the working window as UTC and an Asia/Kolkata rep is
    offered meetings from 15:30 to 23:30 local — every slot wrong, none of them
    obviously so.
    """

    async def test_slots_fall_inside_local_working_hours(self):
        out = await suggest(scheduling_config=IST)
        assert out["suggested_slots"]
        for slot in out["suggested_slots"]:
            local = datetime.fromisoformat(slot["start"])
            assert 10 <= local.hour < 18, f"{slot['start']} is outside 10:00-18:00 local"

    async def test_the_utc_instant_is_offset_correctly(self):
        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"])
        slot = out["recommended_slot"]
        assert slot["start"].endswith("+05:30")
        # 10:00 IST is 04:30 UTC. Getting this wrong by the offset is the whole
        # bug class this module exists to avoid.
        assert datetime.fromisoformat(slot["start_utc"]) == datetime(
            2026, 7, 7, 4, 30, tzinfo=UTC
        )

    async def test_two_tenants_get_different_instants_for_the_same_hour(self):
        india = await suggest(scheduling_config=IST, preferred_days=["Wednesday"])
        us = await suggest(scheduling_config=NY, preferred_days=["Wednesday"])
        assert india["recommended_slot"]["start_utc"] != us["recommended_slot"]["start_utc"]
        for out in (india, us):
            assert datetime.fromisoformat(out["recommended_slot"]["start"]).hour == 10

    async def test_unconfigured_tenant_defaults_to_utc_not_a_guess(self):
        """Slots visibly labelled UTC are fixable; slots silently computed
        against someone else's country are not."""

        out = await suggest(scheduling_config=None)
        assert out["timezone"] == "UTC"
        assert DEFAULT_SCHEDULING["timezone"] == "UTC"

    async def test_local_hour_is_stable_across_a_daylight_saving_change(self):
        """US clocks move on 2026-03-08. 10:00 local is 10:00 local on both
        sides; the UTC instant is what shifts."""

        before = await MeetingSchedulerAgent().run(
            {"scheduling_config": NY, "now": datetime(2026, 3, 4, 12, 0, tzinfo=UTC)}
        )
        after = await MeetingSchedulerAgent().run(
            {"scheduling_config": NY, "now": datetime(2026, 3, 11, 12, 0, tzinfo=UTC)}
        )
        for out in (before, after):
            assert datetime.fromisoformat(out["suggested_slots"][0]["start"]).hour == 10
        offsets = {
            datetime.fromisoformat(out["suggested_slots"][0]["start"]).utcoffset()
            for out in (before, after)
        }
        assert len(offsets) == 2, "the UTC offset should differ either side of the change"

    async def test_weekday_label_is_the_local_one(self):
        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"])
        assert all(slot["weekday"] == "Tuesday" for slot in out["suggested_slots"])


class TestWorkingDays:
    async def test_weekends_are_never_offered(self):
        out = await suggest(scheduling_config=IST, preferred_days=["Saturday", "Sunday"])
        assert out["suggested_slots"] == []
        assert out["limiting_constraint"] == "non_working_day"

    async def test_a_tenant_can_declare_its_own_weekend(self):
        """Friday/Saturday weekends are normal in parts of the world."""

        out = await suggest(
            scheduling_config={**IST, "working_days": [6, 0, 1, 2, 3]},
            preferred_days=["Sunday"],
        )
        assert out["suggested_slots"]


class TestNoticePeriod:
    """"Prefer the earliest available slot" taken literally proposes a demo
    fifteen minutes from now."""

    async def test_nothing_is_offered_inside_the_notice_window(self):
        # 05:00 UTC = 10:30 IST, mid-morning on a working day.
        now = datetime(2026, 7, 7, 5, 0, tzinfo=UTC)
        out = await MeetingSchedulerAgent().run({"scheduling_config": IST, "now": now})
        earliest = datetime.fromisoformat(out["suggested_slots"][0]["start_utc"])
        assert earliest >= now + timedelta(minutes=DEFAULT_SCHEDULING["min_notice_minutes"])

    async def test_a_shorter_notice_period_unlocks_earlier_slots(self):
        now = datetime(2026, 7, 7, 5, 0, tzinfo=UTC)
        strict = await MeetingSchedulerAgent().run({"scheduling_config": IST, "now": now})
        relaxed = await MeetingSchedulerAgent().run(
            {"scheduling_config": {**IST, "min_notice_minutes": 0}, "now": now}
        )
        assert (
            relaxed["suggested_slots"][0]["start_utc"] < strict["suggested_slots"][0]["start_utc"]
        )


class TestBusyAvoidance:
    async def test_an_overlapping_meeting_blocks_the_slot(self):
        blocked = {
            "start": datetime(2026, 7, 7, 4, 30, tzinfo=UTC),  # 10:00 IST
            "end": datetime(2026, 7, 7, 5, 0, tzinfo=UTC),
        }
        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"], busy=[blocked])
        starts = {slot["start_utc"] for slot in out["suggested_slots"]}
        assert blocked["start"].isoformat() not in starts

    async def test_a_slot_may_begin_exactly_when_a_meeting_ends(self):
        """Back-to-back is allowed at booking time (`_check_no_clash` uses
        strict comparisons); the scheduler must agree or it would refuse slots
        that would have saved fine."""

        out = await suggest(
            scheduling_config={**IST, "min_notice_minutes": 0, "slot_spread_minutes": 30},
            preferred_days=["Tuesday"],
            busy=[
                {
                    "start": datetime(2026, 7, 7, 4, 30, tzinfo=UTC),
                    "end": datetime(2026, 7, 7, 5, 0, tzinfo=UTC),
                }
            ],
        )
        starts = {slot["start_utc"] for slot in out["suggested_slots"]}
        assert datetime(2026, 7, 7, 5, 0, tzinfo=UTC).isoformat() in starts

    async def test_a_buffer_pushes_suggestions_clear_of_a_meeting(self):
        out = await suggest(
            scheduling_config={**IST, "buffer_minutes": 30, "min_notice_minutes": 0},
            preferred_days=["Tuesday"],
            busy=[
                {
                    "start": datetime(2026, 7, 7, 4, 30, tzinfo=UTC),
                    "end": datetime(2026, 7, 7, 5, 0, tzinfo=UTC),
                }
            ],
        )
        starts = {slot["start_utc"] for slot in out["suggested_slots"]}
        assert datetime(2026, 7, 7, 5, 0, tzinfo=UTC).isoformat() not in starts

    async def test_a_fully_booked_day_reports_why(self):
        full = [
            {
                "start": datetime(2026, 7, 7, 4, 30, tzinfo=UTC),
                "end": datetime(2026, 7, 7, 12, 30, tzinfo=UTC),
            }
        ]
        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"], busy=full)
        # The following Tuesday is still free, so restrict the horizon to one week.
        out = await suggest(
            scheduling_config={**IST, "search_horizon_days": 5},
            preferred_days=["Tuesday"],
            busy=full,
        )
        assert out["suggested_slots"] == []
        assert out["limiting_constraint"] == "busy"
        assert "already booked" in out["explanation"]

    async def test_malformed_busy_windows_are_ignored_not_crashed_on(self):
        out = await suggest(
            scheduling_config=IST,
            busy=[
                {"start": datetime(2026, 7, 7, 6, 0, tzinfo=UTC), "end": datetime(2026, 7, 7, 5, 0, tzinfo=UTC)},
                {"start": datetime(2026, 7, 7, 6, 0, tzinfo=UTC), "end": datetime(2026, 7, 7, 6, 0, tzinfo=UTC)},
            ],
        )
        assert out["suggested_slots"]


class TestSpread:
    async def test_same_day_suggestions_are_not_the_adjacent_half_hour(self):
        """10:00 and 10:30 is the same slot twice, not a choice. The brief's
        own example spreads across the day."""

        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"])
        same_day = [
            datetime.fromisoformat(s["start_utc"])
            for s in out["suggested_slots"]
            if s["start"].startswith("2026-07-07")
        ]
        for earlier, later in zip(same_day, same_day[1:], strict=False):
            assert later - earlier >= timedelta(
                minutes=DEFAULT_SCHEDULING["slot_spread_minutes"]
            )

    async def test_a_day_is_capped_so_other_days_get_a_look_in(self):
        out = await suggest(scheduling_config=IST)
        by_day: dict[str, int] = {}
        for slot in out["suggested_slots"]:
            by_day[slot["start"][:10]] = by_day.get(slot["start"][:10], 0) + 1
        assert max(by_day.values()) <= DEFAULT_SCHEDULING["max_slots_per_day"]

    async def test_the_list_is_capped(self):
        out = await suggest(scheduling_config=IST)
        assert len(out["suggested_slots"]) <= DEFAULT_SCHEDULING["max_slots"]


class TestPreferredDays:
    async def test_the_requested_day_is_honoured_strictly(self):
        """Offering Thursday to a customer who asked for Tuesday reads as the
        agent ignoring them."""

        out = await suggest(scheduling_config=IST, preferred_days=["Tuesday"])
        assert {s["weekday"] for s in out["suggested_slots"]} == {"Tuesday"}

    async def test_abbreviations_resolve(self):
        for spelling in ("tue", "Tues", "TUESDAY"):
            out = await suggest(scheduling_config=IST, preferred_days=[spelling])
            assert {s["weekday"] for s in out["suggested_slots"]} == {"Tuesday"}

    async def test_an_unknown_day_is_rejected_not_ignored(self):
        """Silently dropping the day the customer named and offering any day
        is worse than an error."""

        with pytest.raises(SchedulingConfigError, match="Tuseday"):
            await suggest(scheduling_config=IST, preferred_days=["Tuseday"])

    async def test_no_preference_spans_several_days(self):
        out = await suggest(scheduling_config=IST)
        assert len({s["start"][:10] for s in out["suggested_slots"]}) > 1

    def test_weekday_parsing(self):
        assert parse_weekdays(["Monday", "fri"]) == [0, 4]
        assert parse_weekdays(None) == []
        assert parse_weekdays(["Tuesday", "tue"]) == [1], "duplicates collapse"


class TestDuration:
    async def test_slot_length_matches_the_request(self):
        out = await suggest(scheduling_config=IST, duration_minutes=45)
        slot = out["recommended_slot"]
        length = datetime.fromisoformat(slot["end_utc"]) - datetime.fromisoformat(
            slot["start_utc"]
        )
        assert length == timedelta(minutes=45)
        assert out["duration_minutes"] == 45

    async def test_a_meeting_never_runs_past_the_working_day(self):
        out = await suggest(scheduling_config=IST, duration_minutes=120)
        for slot in out["suggested_slots"]:
            assert datetime.fromisoformat(slot["end"]).hour <= 18

    async def test_the_tenant_default_is_used_when_unspecified(self):
        out = await suggest(scheduling_config={**IST, "default_duration_minutes": 60})
        assert out["duration_minutes"] == 60

    @pytest.mark.parametrize("bad", [0, -30, 10_000, "half an hour"])
    async def test_nonsense_durations_are_rejected(self, bad):
        """A non-positive duration produces an infinite slot grid; a multi-day
        one produces none, silently."""

        with pytest.raises(SchedulingConfigError):
            await suggest(scheduling_config=IST, duration_minutes=bad)

    def test_duration_bounds(self):
        assert validate_duration("30") == 30
        with pytest.raises(SchedulingConfigError):
            validate_duration(1)


class TestConfigValidation:
    """A bad config must fail loudly. Falling back silently moves every
    suggested meeting by hours with nothing to show for it."""

    @pytest.mark.parametrize(
        "config,match",
        [
            ({"timezone": "Mars/Olympus"}, "Unknown timezone"),
            ({"work_start": "18:00", "work_end": "10:00"}, "must be after"),
            ({"work_start": "nine"}, "HH:MM"),
            ({"working_days": []}, "empty"),
            ({"working_days": [0, 9]}, "0 \\(Monday\\)"),
            ({"max_slots": 0}, "at least 1"),
        ],
    )
    def test_invalid_config_is_rejected(self, config, match):
        with pytest.raises(SchedulingConfigError, match=match):
            resolve_config(config)

    def test_partial_config_keeps_the_defaults(self):
        resolved = resolve_config({"timezone": "Asia/Kolkata"})
        assert resolved["timezone"] == "Asia/Kolkata"
        assert resolved["work_start"].hour == 10
        assert resolved["working_days"] == DEFAULT_SCHEDULING["working_days"]


class TestFreeWindows:
    def test_overlapping_meetings_are_merged_before_subtraction(self):
        """Without merging, two overlapping meetings each carve their own gap
        and produce a 'free' window between them that is not free."""

        start = datetime(2026, 7, 7, 4, 30, tzinfo=UTC)
        end = datetime(2026, 7, 7, 12, 30, tzinfo=UTC)
        busy = [
            Busy(datetime(2026, 7, 7, 5, 0, tzinfo=UTC), datetime(2026, 7, 7, 7, 0, tzinfo=UTC)),
            Busy(datetime(2026, 7, 7, 6, 0, tzinfo=UTC), datetime(2026, 7, 7, 8, 0, tzinfo=UTC)),
        ]
        free = free_windows(start=start, end=end, busy=busy, buffer=timedelta(0))
        assert free == [
            (start, datetime(2026, 7, 7, 5, 0, tzinfo=UTC)),
            (datetime(2026, 7, 7, 8, 0, tzinfo=UTC), end),
        ]

    def test_a_fully_booked_window_has_no_free_time(self):
        start = datetime(2026, 7, 7, 4, 30, tzinfo=UTC)
        end = datetime(2026, 7, 7, 12, 30, tzinfo=UTC)
        assert free_windows(start=start, end=end, busy=[Busy(start, end)], buffer=timedelta(0)) == []

    def test_an_empty_calendar_is_one_free_window(self):
        start = datetime(2026, 7, 7, 4, 30, tzinfo=UTC)
        end = datetime(2026, 7, 7, 12, 30, tzinfo=UTC)
        assert free_windows(start=start, end=end, busy=[], buffer=timedelta(0)) == [(start, end)]


class TestOutputContract:
    async def test_model_version_is_reported(self):
        assert (await suggest(scheduling_config=IST))["model_version"] == MODEL_VERSION

    async def test_recommendation_is_the_earliest_suggestion(self):
        out = await suggest(scheduling_config=IST)
        assert out["recommended_slot"] == out["suggested_slots"][0]

    async def test_no_slots_means_a_null_recommendation_not_a_fabricated_one(self):
        out = await suggest(scheduling_config=IST, preferred_days=["Sunday"])
        assert out["recommended_slot"] is None
        assert out["suggested_slots"] == []

    async def test_availability_source_is_declared(self):
        """Until the calendar integration lands, "free" means "nothing booked
        in this system" — a rep's Google standup is invisible to us."""

        assert (await suggest(scheduling_config=IST))["availability_sources"] == ["internal"]


# ------------------------------------------------------------------ API layer


async def set_scheduling(db, tenant, config: dict) -> None:
    from app.models.company import Company

    company = await db.get(Company, tenant.company_id)
    company.scheduling_config = config
    await db.commit()


class TestSuggestSlotsEndpoint:
    async def test_returns_slots_for_the_calling_rep(self, client, db, tenant):
        await set_scheduling(db, tenant, IST)
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["timezone"] == "Asia/Kolkata"
        assert data["suggested_slots"]
        assert data["recommended_slot"] == data["suggested_slots"][0]

    async def test_a_suggested_slot_is_actually_bookable(self, client, db, tenant):
        """The property that makes the feature worth having: the scheduler and
        `_check_no_clash` must apply the same rules, or every suggestion is
        rejected on save."""

        await set_scheduling(db, tenant, IST)
        headers = tenant.headers("sales_executive")
        slot = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id), "duration_minutes": 30},
            headers=headers,
        ).json()["data"]["recommended_slot"]

        created = client.post(
            f"{V1}/meetings/",
            json={
                "lead_id": str(tenant.lead_id),
                "scheduled_at": slot["start_utc"],
                "ends_at": slot["end_utc"],
            },
            headers=headers,
        )
        assert created.status_code == 201, created.text

    async def test_a_booked_slot_stops_being_suggested(self, client, db, tenant):
        await set_scheduling(db, tenant, IST)
        headers = tenant.headers("sales_executive")
        body = {"lead_id": str(tenant.lead_id)}
        slot = client.post(
            f"{V1}/meetings/suggest-slots", json=body, headers=headers
        ).json()["data"]["recommended_slot"]
        client.post(
            f"{V1}/meetings/",
            json={
                "lead_id": str(tenant.lead_id),
                "scheduled_at": slot["start_utc"],
                "ends_at": slot["end_utc"],
            },
            headers=headers,
        )
        again = client.post(f"{V1}/meetings/suggest-slots", json=body, headers=headers)
        starts = {s["start_utc"] for s in again.json()["data"]["suggested_slots"]}
        assert slot["start_utc"] not in starts

    async def test_a_cancelled_meeting_frees_its_slot_again(self, client, db, tenant):
        await set_scheduling(db, tenant, IST)
        headers = tenant.headers("sales_executive")
        body = {"lead_id": str(tenant.lead_id)}
        slot = client.post(
            f"{V1}/meetings/suggest-slots", json=body, headers=headers
        ).json()["data"]["recommended_slot"]
        meeting_id = client.post(
            f"{V1}/meetings/",
            json={
                "lead_id": str(tenant.lead_id),
                "scheduled_at": slot["start_utc"],
                "ends_at": slot["end_utc"],
            },
            headers=headers,
        ).json()["data"]["id"]
        client.delete(f"{V1}/meetings/{meeting_id}", headers=headers)

        again = client.post(f"{V1}/meetings/suggest-slots", json=body, headers=headers)
        starts = {s["start_utc"] for s in again.json()["data"]["suggested_slots"]}
        assert slot["start_utc"] in starts

    async def test_empty_result_names_the_constraint_to_relax(self, client, db, tenant):
        """A bare "0 slots" is unactionable."""

        await set_scheduling(db, tenant, IST)
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id), "preferred_days": ["Sunday"]},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200
        assert r.json()["data"]["suggested_slots"] == []
        assert r.json()["data"]["limiting_constraint"] == "non_working_day"
        assert "limiting_constraint" in r.json()["message"]

    async def test_broken_tenant_config_is_422_not_500(self, client, db, tenant):
        await set_scheduling(db, tenant, {"timezone": "Mars/Olympus"})
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_SCHEDULING_CONFIG"

    async def test_bad_day_name_is_a_request_error(self, client, db, tenant):
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id), "preferred_days": ["Tuseday"]},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_SCHEDULING_REQUEST"

    async def test_contact_from_another_lead_is_rejected(self, client, db, tenant, other_tenant):
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id), "contact_id": str(other_tenant.contact_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "CONTACT_LEAD_MISMATCH"

    async def test_cross_tenant_lead_is_404(self, client, db, tenant, other_tenant):
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(other_tenant.lead_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 404

    async def test_unassigned_executive_is_404(self, client, db, tenant):
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("sales_executive_2"),
        )
        assert r.status_code == 404

    async def test_marketing_has_no_access(self, client, db, tenant):
        r = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("marketing"),
        )
        assert r.status_code == 403

    async def test_another_reps_meetings_do_not_block_my_slots(self, client, db, tenant):
        """Busy time is scoped to the owner — a slot is unavailable because
        *this* rep is busy, not because someone in the tenant is."""

        from app.models.meeting import Meeting

        await set_scheduling(db, tenant, IST)
        headers = tenant.headers("sales_executive")
        slot = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=headers,
        ).json()["data"]["recommended_slot"]

        db.add(
            Meeting(
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                owner_id=tenant.exec2_id,
                scheduled_at=datetime.fromisoformat(slot["start_utc"]),
                ends_at=datetime.fromisoformat(slot["end_utc"]),
            )
        )
        await db.commit()

        again = client.post(
            f"{V1}/meetings/suggest-slots",
            json={"lead_id": str(tenant.lead_id)},
            headers=headers,
        )
        starts = {s["start_utc"] for s in again.json()["data"]["suggested_slots"]}
        assert slot["start_utc"] in starts


class TestAvailabilityEndpoint:
    async def test_reports_working_hours_and_free_time(self, client, db, tenant):
        await set_scheduling(db, tenant, IST)
        r = client.get(
            f"{V1}/meetings/availability?date=2026-07-07",
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["timezone"] == "Asia/Kolkata"
        assert data["is_working_day"] is True
        assert data["working_hours"]["start"].startswith("2026-07-07T10:00")
        assert data["free"] == [data["working_hours"]]
        assert data["availability_sources"] == ["internal"]

    async def test_a_booked_meeting_appears_as_busy(self, client, db, tenant):
        from app.models.meeting import Meeting

        await set_scheduling(db, tenant, IST)
        db.add(
            Meeting(
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                owner_id=tenant.exec_id,
                scheduled_at=datetime(2026, 7, 7, 5, 0, tzinfo=UTC),
                ends_at=datetime(2026, 7, 7, 6, 0, tzinfo=UTC),
            )
        )
        await db.commit()

        data = client.get(
            f"{V1}/meetings/availability?date=2026-07-07",
            headers=tenant.headers("sales_executive"),
        ).json()["data"]
        assert len(data["busy"]) == 1
        assert data["busy"][0]["start"].startswith("2026-07-07T10:30")
        assert len(data["free"]) == 2, "the day splits either side of the meeting"

    async def test_a_weekend_is_flagged(self, client, db, tenant):
        await set_scheduling(db, tenant, IST)
        data = client.get(
            f"{V1}/meetings/availability?date=2026-07-11",  # Saturday
            headers=tenant.headers("sales_executive"),
        ).json()["data"]
        assert data["is_working_day"] is False

    async def test_a_malformed_date_is_422(self, client, tenant):
        r = client.get(
            f"{V1}/meetings/availability?date=07-07-2026",
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_DATE"
