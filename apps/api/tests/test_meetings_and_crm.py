"""Meetings (scheduling rules) and CRM history (activities, notes)."""

import pytest
from sqlalchemy import text

MEETINGS = "/api/v1/meetings"
LEADS = "/api/v1/leads"


def slot(hour: int, length: int = 1) -> dict:
    return {
        "scheduled_at": f"2026-09-01T{hour:02d}:00:00Z",
        "ends_at": f"2026-09-01T{hour + length:02d}:00:00Z",
    }


@pytest.fixture
def meeting(client, tenant):
    r = client.post(
        f"{MEETINGS}/",
        json={"lead_id": str(tenant.lead_id), "title": "Demo", "meeting_type": "demo", **slot(10)},
        headers=tenant.headers("sales_executive"),
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


class TestTimeWindow:
    def test_end_must_be_after_start(self, client, tenant):
        r = client.post(
            f"{MEETINGS}/",
            json={
                "lead_id": str(tenant.lead_id),
                "title": "Backwards",
                "scheduled_at": "2026-09-01T14:00:00Z",
                "ends_at": "2026-09-01T13:00:00Z",
            },
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_TIME_WINDOW"

    def test_zero_length_rejected(self, client, tenant):
        r = client.post(
            f"{MEETINGS}/",
            json={
                "lead_id": str(tenant.lead_id),
                "title": "Instant",
                "scheduled_at": "2026-09-01T14:00:00Z",
                "ends_at": "2026-09-01T14:00:00Z",
            },
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422

    def test_rescheduling_into_an_invalid_window_is_422_not_500(self, client, tenant, meeting):
        """Comparing an inbound aware datetime against a stored naive one used
        to raise TypeError and surface as a 500."""

        r = client.put(
            f"{MEETINGS}/{meeting['id']}",
            json={"ends_at": "2026-09-01T09:00:00Z"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422


class TestDoubleBooking:
    def test_overlapping_booking_rejected(self, client, tenant, meeting):
        r = client.post(
            f"{MEETINGS}/",
            json={"lead_id": str(tenant.lead_id), "title": "Clash", **slot(10)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "MEETING_CONFLICT"
        assert r.json()["details"]["conflicting_meeting_id"] == meeting["id"]

    def test_back_to_back_allowed(self, client, tenant, meeting):
        """One ending exactly as the next begins is not an overlap."""

        r = client.post(
            f"{MEETINGS}/",
            json={"lead_id": str(tenant.lead_id), "title": "Next", **slot(11)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 201, r.text

    def test_cancelled_meeting_frees_its_slot(self, client, tenant, meeting):
        client.delete(f"{MEETINGS}/{meeting['id']}", headers=tenant.headers("sales_executive"))
        r = client.post(
            f"{MEETINGS}/",
            json={"lead_id": str(tenant.lead_id), "title": "Reuse", **slot(10)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 201, r.text


class TestAttendee:
    def test_contact_must_belong_to_the_lead(self, client, tenant, other_tenant):
        r = client.post(
            f"{MEETINGS}/",
            json={
                "lead_id": str(tenant.lead_id),
                "title": "Wrong person",
                "contact_id": str(other_tenant.contact_id),
                **slot(15),
            },
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "CONTACT_LEAD_MISMATCH"


class TestUpdateDoesNotWipeNotes:
    def test_changing_title_keeps_notes(self, client, tenant, meeting):
        """PUT reused MeetingCreate, so omitting notes blanked them."""

        client.put(
            f"{MEETINGS}/{meeting['id']}",
            json={"notes": "Bring the pricing deck"},
            headers=tenant.headers("sales_executive"),
        )
        r = client.put(
            f"{MEETINGS}/{meeting['id']}",
            json={"title": "Demo v2"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.json()["data"]["notes"] == "Bring the pricing deck"
        assert r.json()["data"]["title"] == "Demo v2"


class TestOutcome:
    def test_outcome_completes_the_meeting(self, client, tenant, meeting):
        r = client.post(
            f"{MEETINGS}/{meeting['id']}/outcome",
            json={"outcome": "demo_completed", "next_action": "send_proposal"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "completed"

    def test_outcome_is_idempotent(self, client, tenant, meeting):
        body = {"outcome": "demo_completed"}
        client.post(f"{MEETINGS}/{meeting['id']}/outcome", json=body, headers=tenant.headers("sales_executive"))
        r = client.post(f"{MEETINGS}/{meeting['id']}/outcome", json=body, headers=tenant.headers("sales_executive"))
        assert r.status_code == 422
        assert r.json()["error_code"] == "OUTCOME_ALREADY_RECORDED"

    async def test_forecast_job_is_deduped(self, client, tenant, meeting, db):
        body = {"outcome": "demo_completed"}
        client.post(f"{MEETINGS}/{meeting['id']}/outcome", json=body, headers=tenant.headers("sales_executive"))
        client.post(f"{MEETINGS}/{meeting['id']}/outcome", json=body, headers=tenant.headers("sales_executive"))
        count = (
            await db.execute(text("SELECT count(*) FROM jobs WHERE job_type='revenue_forecast'"))
        ).scalar()
        assert count == 1

    def test_completed_meeting_is_frozen(self, client, tenant, meeting):
        client.post(
            f"{MEETINGS}/{meeting['id']}/outcome",
            json={"outcome": "demo_completed"},
            headers=tenant.headers("sales_executive"),
        )
        assert client.put(
            f"{MEETINGS}/{meeting['id']}", json={"title": "late"}, headers=tenant.headers("sales_executive")
        ).status_code == 422
        assert client.delete(
            f"{MEETINGS}/{meeting['id']}", headers=tenant.headers("sales_executive")
        ).status_code == 422


class TestMeetingRoles:
    def test_marketing_has_no_access_at_all(self, client, tenant):
        assert client.get(f"{MEETINGS}/", headers=tenant.headers("marketing")).status_code == 403

    def test_manager_reads_but_cannot_book(self, client, tenant):
        assert client.get(f"{MEETINGS}/", headers=tenant.headers("sales_manager")).status_code == 200
        r = client.post(
            f"{MEETINGS}/",
            json={"lead_id": str(tenant.lead_id), "title": "x", **slot(20)},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 403


class TestTimeline:
    async def test_booking_and_outcome_both_log_activities(self, client, tenant, meeting, db):
        client.post(
            f"{MEETINGS}/{meeting['id']}/outcome",
            json={"outcome": "demo_completed"},
            headers=tenant.headers("sales_executive"),
        )
        kinds = (await db.execute(text("SELECT activity_type FROM crm_activities"))).scalars().all()
        assert "meeting_scheduled" in kinds
        assert "meeting_outcome" in kinds


class TestNotes:
    @pytest.fixture
    def note(self, client, tenant):
        r = client.post(
            f"{LEADS}/{tenant.lead_id}/notes",
            json={"body": "Rahul wants pricing before Friday"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 201, r.text
        return r.json()["data"]

    def test_author_can_edit_their_own_note(self, client, tenant, note):
        r = client.put(
            f"{LEADS}/notes/{note['id']}",
            json={"body": "…before NEXT Friday"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text

    def test_even_a_manager_cannot_rewrite_someone_elses_note(self, client, tenant, note):
        """The note keeps showing its author's name, so an edit by anyone else
        puts words in their mouth."""

        r = client.put(
            f"{LEADS}/notes/{note['id']}",
            json={"body": "Manager rewrite"},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 403
        assert r.json()["error_code"] == "NOT_NOTE_AUTHOR"

    def test_manager_may_delete_any_note(self, client, tenant, note):
        """Deleting is moderation, which is a different judgement to rewriting."""

        r = client.delete(f"{LEADS}/notes/{note['id']}", headers=tenant.headers("sales_manager"))
        assert r.status_code == 200, r.text

    def test_isolation_answers_before_authorship(self, client, tenant, note):
        """An unassigned rep gets 404, not 403 — they must not learn it exists."""

        r = client.put(
            f"{LEADS}/notes/{note['id']}",
            json={"body": "nope"},
            headers=tenant.headers("sales_executive_2"),
        )
        assert r.status_code == 404


class TestActivities:
    def test_activity_is_append_only(self, client, tenant):
        """No PUT or DELETE exists: correcting history means logging a new
        event, not rewriting the log."""

        r = client.post(
            f"{LEADS}/{tenant.lead_id}/activities",
            json={"activity_type": "call", "description": "Discussed pricing"},
            headers=tenant.headers("sales_executive"),
        )
        activity_id = r.json()["data"]["id"]
        assert client.put(
            f"{LEADS}/activities/{activity_id}", json={}, headers=tenant.headers("sales_executive")
        ).status_code in (404, 405)
        assert client.delete(
            f"{LEADS}/activities/{activity_id}", headers=tenant.headers("sales_executive")
        ).status_code in (404, 405)

    def test_deal_must_belong_to_the_same_lead(self, client, tenant, other_tenant):
        r = client.post(
            f"{LEADS}/{tenant.lead_id}/activities",
            json={
                "activity_type": "call",
                "description": "x",
                "deal_id": "00000000-0000-0000-0000-000000000009",
            },
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "DEAL_LEAD_MISMATCH"
