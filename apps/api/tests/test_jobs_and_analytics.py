"""AI job lifecycle and dashboard analytics."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.models.deal import Deal, DealStage
from app.models.job import Job, JobStatus
from app.models.lead import Lead, LeadPriority
from app.models.meeting import Meeting, MeetingStatus

V1 = "/api/v1"


class _FakeTask:
    """Stands in for the Celery task so tests never need a broker."""

    def __init__(self):
        self.calls: list[tuple] = []

    def delay(self, *args):
        self.calls.append(args)


class _DeadTask:
    def delay(self, *args):
        raise ConnectionError("broker unreachable")


@pytest.fixture
def fake_task(monkeypatch):
    task = _FakeTask()
    monkeypatch.setattr("app.routers.ai.run_lead_intelligence", task)
    return task


class TestJobDispatch:
    def test_job_is_created_and_dispatched_once(self, client, tenant, fake_task):
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code in (200, 202), r.text
        assert len(fake_task.calls) == 1

    def test_double_click_returns_the_same_job(self, client, tenant, fake_task):
        """Two clicks would otherwise run the full pipeline twice: duplicate
        rows in every AI output table and twice the LLM spend."""

        first = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        ).json()["data"]["job_id"]
        second = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        )
        assert second.json()["data"]["job_id"] == first
        assert "already running" in second.json()["message"]
        assert len(fake_task.calls) == 1, "no duplicate dispatch"

    def test_unreachable_broker_is_503_not_500(self, client, tenant, monkeypatch):
        monkeypatch.setattr("app.routers.ai.run_lead_intelligence", _DeadTask())
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 503
        assert r.json()["error_code"] == "QUEUE_UNAVAILABLE"

    async def test_failed_dispatch_marks_the_job_failed(self, client, tenant, monkeypatch, db):
        """Otherwise the row sits in `pending` forever — a spinner the user can
        never clear."""

        monkeypatch.setattr("app.routers.ai.run_lead_intelligence", _DeadTask())
        client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        )
        rows = (await db.execute(text("SELECT status, error_message FROM jobs"))).all()
        assert len(rows) == 1
        assert rows[0][0] == "failed"
        assert rows[0][1]

    def test_both_job_endpoints_agree(self, client, tenant, fake_task):
        """/jobs/{id} (frontend polling) and /ai/jobs/{id} (AI Center) share a
        service so they cannot drift."""

        job_id = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/run-intelligence",
            headers=tenant.headers("sales_manager"),
        ).json()["data"]["job_id"]

        short = client.get(f"{V1}/jobs/{job_id}", headers=tenant.headers("sales_manager"))
        long = client.get(f"{V1}/ai/jobs/{job_id}", headers=tenant.headers("sales_manager"))
        assert short.status_code == long.status_code == 200
        assert short.json()["data"] == long.json()["data"]

    def test_unknown_agent_is_404(self, client, tenant):
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/not-a-real-agent",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 404


@pytest.fixture
async def analytics_data(db, tenant):
    """A deliberately awkward dataset: archived rows, two currencies, a
    cancelled meeting, and jobs in every state."""

    archived_lead = Lead(
        company_id=tenant.company_id,
        name="Archived",
        owner_id=tenant.exec_id,
        priority=LeadPriority.HIGH,
        archived_at=datetime.now(UTC),
    )
    high_lead = Lead(
        company_id=tenant.company_id,
        name="Hot",
        owner_id=tenant.exec_id,
        priority=LeadPriority.HIGH,
    )
    db.add_all([archived_lead, high_lead])
    await db.flush()

    db.add_all(
        [
            Deal(company_id=tenant.company_id, lead_id=tenant.lead_id, name="open-usd",
                 stage=DealStage.NEGOTIATION, amount=Decimal("1000.50"), currency="USD"),
            Deal(company_id=tenant.company_id, lead_id=tenant.lead_id, name="open-inr",
                 stage=DealStage.QUALIFIED, amount=Decimal("80000.25"), currency="INR"),
            Deal(company_id=tenant.company_id, lead_id=tenant.lead_id, name="won",
                 stage=DealStage.CLOSED_WON, amount=Decimal("500.25"), currency="USD"),
            Deal(company_id=tenant.company_id, lead_id=tenant.lead_id, name="archived-deal",
                 stage=DealStage.NEGOTIATION, amount=Decimal("777.77"), currency="USD",
                 archived_at=datetime.now(UTC)),
            Deal(company_id=tenant.company_id, lead_id=archived_lead.id, name="on-archived-lead",
                 stage=DealStage.NEGOTIATION, amount=Decimal("666.66"), currency="USD"),
            Meeting(company_id=tenant.company_id, lead_id=tenant.lead_id, owner_id=tenant.exec_id,
                    title="live", scheduled_at=datetime.now(UTC), ends_at=datetime.now(UTC),
                    status=MeetingStatus.SCHEDULED),
            Meeting(company_id=tenant.company_id, lead_id=tenant.lead_id, owner_id=tenant.exec_id,
                    title="cancelled", scheduled_at=datetime.now(UTC), ends_at=datetime.now(UTC),
                    status=MeetingStatus.CANCELLED),
        ]
    )
    for status in (JobStatus.COMPLETED, JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.PENDING):
        db.add(Job(company_id=tenant.company_id, job_type="lead_intelligence",
                   lead_id=tenant.lead_id, status=status))
    await db.commit()
    return tenant


class TestDashboard:
    """Analytics must agree with the pages beside it — an archived lead cannot
    keep inflating the totals."""

    def test_archived_rows_are_excluded(self, client, analytics_data):
        d = client.get(f"{V1}/analytics/dashboard", headers=analytics_data.headers("sales_manager")).json()["data"]
        assert d["total_leads"] == 2, "the archived lead must not count"
        assert d["high_priority_leads"] == 1
        assert d["open_deals"] == 2, "excludes the archived deal and the one on the archived lead"

    def test_money_is_exact_and_per_currency(self, client, analytics_data):
        d = client.get(f"{V1}/analytics/dashboard", headers=analytics_data.headers("sales_manager")).json()["data"]
        pipeline = d["pipeline_value_by_currency"]
        assert set(pipeline) == {"USD", "INR"}, "summing across currencies is meaningless"
        assert Decimal(pipeline["USD"]) == Decimal("1000.50")
        assert Decimal(d["won_value_by_currency"]["USD"]) == Decimal("500.25")

    def test_cancelled_meetings_are_not_scheduled(self, client, analytics_data):
        d = client.get(f"{V1}/analytics/dashboard", headers=analytics_data.headers("sales_manager")).json()["data"]
        assert d["meetings_scheduled"] == 1

    def test_job_counts(self, client, analytics_data):
        d = client.get(f"{V1}/analytics/dashboard", headers=analytics_data.headers("sales_manager")).json()["data"]
        assert (d["ai_jobs_completed"], d["ai_jobs_failed"], d["ai_jobs_in_flight"]) == (2, 1, 1)

    def test_exec_dashboard_is_scoped_to_their_leads(self, client, analytics_data):
        url = f"{V1}/analytics/dashboard"
        mgr = client.get(url, headers=analytics_data.headers("sales_manager")).json()["data"]
        other = client.get(url, headers=analytics_data.headers("sales_executive_2")).json()["data"]
        assert other["total_leads"] == 0 < mgr["total_leads"]


class TestAnalyticsRoles:
    @pytest.mark.parametrize("path", ["revenue", "team-performance"])
    def test_exec_cannot_see_manager_reports(self, client, tenant, path):
        assert client.get(f"{V1}/analytics/{path}", headers=tenant.headers("sales_executive")).status_code == 403

    def test_manager_can(self, client, tenant):
        assert client.get(f"{V1}/analytics/revenue", headers=tenant.headers("sales_manager")).status_code == 200


class TestFunnel:
    def test_every_stage_present_even_at_zero(self, client, tenant):
        """A funnel that changes shape as data arrives is unreadable."""

        data = client.get(f"{V1}/analytics/funnel", headers=tenant.headers("sales_manager")).json()["data"]
        assert [s["stage"] for s in data] == [
            "new", "qualified", "demo_scheduled", "proposal_sent",
            "negotiation", "closed_won", "closed_lost",
        ]


class TestTeamPerformance:
    def test_rows_carry_names_not_bare_ids(self, client, tenant):
        rows = client.get(f"{V1}/analytics/team-performance", headers=tenant.headers("sales_manager")).json()["data"]
        assert rows and all(r["full_name"] for r in rows)

    def test_includes_reps_with_no_leads(self, client, tenant):
        """A team view that hides idle reps is the wrong view."""

        rows = client.get(f"{V1}/analytics/team-performance", headers=tenant.headers("sales_manager")).json()["data"]
        assert str(tenant.exec2_id) in {r["user_id"] for r in rows}
