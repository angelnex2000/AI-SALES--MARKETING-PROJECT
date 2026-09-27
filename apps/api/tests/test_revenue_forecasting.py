"""Revenue Forecasting Agent — arithmetic, honesty of the confidence number,
currency separation, and the API contract.

The rule under test throughout: this is the figure a Sales Manager quotes
upward, so every way it can be quietly wrong — a summed multi-currency total,
overdue pipeline counted twice, float money, a confidence nobody measured —
gets a test.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from agents.forecasting import features
from agents.forecasting import model as forecast_model
from agents.forecasting.model import (
    MAX_CONFIDENCE,
    MODEL_VERSION,
    UNCALIBRATED_CONFIDENCE,
    RevenueForecastingAgent,
)
from agents.forecasting.train import measured_win_rate, regression_metrics, rescale_rates
from app.services import forecast_service

V1 = "/api/v1"

AUGUST = ("2026-08", datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC))
AS_OF = datetime(2026, 8, 5, tzinfo=UTC)

# A calibration with round numbers so the arithmetic in these tests is
# checkable by hand.
CALIBRATION = {
    "rates": {"new": 0.10, "qualified": 0.20, "proposal_sent": 0.50, "negotiation": 0.80},
    "support": {"new": 500, "qualified": 500, "proposal_sent": 500, "negotiation": 500},
}
METRICS = {"backtest": {"weighted_pipeline": {"mape": 0.20}}}


@pytest.fixture(autouse=True)
def artifacts(monkeypatch):
    """Pin the artifacts.

    `model._load()` caches whatever `agents/forecasting/artifacts/` holds, and
    those files exist only if someone has run training — so without this the
    suite would pass or fail depending on the developer's working copy.
    """

    monkeypatch.setattr(
        forecast_model, "_artifact_cache", {"calibration": CALIBRATION, "metrics": METRICS}
    )


def deal(amount, stage="proposal_sent", close="2026-08-20", **extra):
    return {
        "id": extra.pop("id", "d1"),
        "name": extra.pop("name", "Deal"),
        "stage": stage,
        "amount": amount,
        "expected_close_date": None if close is None else datetime.fromisoformat(f"{close}T00:00:00+00:00"),
        **extra,
    }


async def forecast(open_deals=None, committed="0", history=None, period=None, as_of=AS_OF):
    name, start, end = AUGUST
    return await RevenueForecastingAgent().run(
        {
            "forecast_period": period or name,
            "currency": "INR",
            "period_start": start,
            "period_end": end,
            "as_of": as_of,
            "committed_revenue": committed,
            "open_deals": open_deals or [],
            "history": history or [],
        }
    )


class TestWeightedPipeline:
    async def test_expected_value_is_amount_times_win_rate(self):
        out = await forecast([deal("100000", stage="proposal_sent")])
        assert out["weighted_pipeline"] == "50000.00"

    async def test_stages_are_weighted_differently(self):
        early = await forecast([deal("100000", stage="new")])
        late = await forecast([deal("100000", stage="negotiation")])
        assert Decimal(early["weighted_pipeline"]) < Decimal(late["weighted_pipeline"])

    async def test_committed_revenue_is_added_at_full_value(self):
        """Already-won revenue is banked; weighting it would forecast less
        money than the company has demonstrably made."""

        out = await forecast([deal("100000", stage="proposal_sent")], committed="250000")
        assert out["predicted_revenue"] == "300000.00"
        assert out["committed_revenue"] == "250000.00"

    async def test_money_arithmetic_is_exact(self):
        """0.10 has no exact binary representation, and these values are summed
        across a whole pipeline — the reason `Deal.amount` is NUMERIC."""

        out = await forecast(
            [deal("0.10", stage="proposal_sent", id=f"d{i}") for i in range(3)]
        )
        assert out["weighted_pipeline"] == "0.15"
        assert Decimal(out["predicted_revenue"]) == Decimal("0.15")

    async def test_money_leaves_the_agent_as_strings_not_floats(self):
        """The payload is logged to AIInteractionLog as JSON; a float here
        would reintroduce exactly the error the NUMERIC column avoids."""

        out = await forecast([deal("100000")])
        for key in ("predicted_revenue", "committed_revenue", "weighted_pipeline"):
            assert isinstance(out[key], str)


class TestExcludedPipeline:
    async def test_overdue_deals_are_excluded_and_reported(self):
        """Counting deals that already missed their close date is the single
        largest source of optimistic bias in hand-built forecasts."""

        out = await forecast([deal("100000", close="2026-07-15")])
        assert out["weighted_pipeline"] == "0.00"
        assert out["breakdown"]["excluded"]["overdue_deals"] == 1
        assert out["breakdown"]["excluded"]["overdue_value"] == "100000"
        assert any("past their expected close date" in w for w in out["warnings"])

    async def test_deals_without_a_close_date_are_reported_not_silently_dropped(self):
        """Otherwise a pipeline that nobody has dated reads as a collapse
        rather than as missing data."""

        out = await forecast([deal("100000", close=None)])
        assert out["breakdown"]["excluded"]["no_close_date_deals"] == 1
        assert any("no expected close date" in w for w in out["warnings"])

    async def test_deals_in_a_later_period_do_not_count(self):
        out = await forecast([deal("100000", close="2026-10-01")])
        assert out["weighted_pipeline"] == "0.00"

    async def test_a_deal_with_no_amount_is_counted_as_a_gap(self):
        out = await forecast([deal(None), deal("100000", id="d2")])
        assert out["breakdown"]["excluded"]["missing_amount_deals"] == 1
        assert out["breakdown"]["amount_coverage"] == 0.5
        assert any("no amount" in w for w in out["warnings"])

    async def test_an_empty_pipeline_says_so(self):
        out = await forecast([], committed="50000")
        assert out["predicted_revenue"] == "50000.00"
        assert any("committed revenue only" in w for w in out["warnings"])


class TestConfidence:
    """The brief reports 0.87 beside a number nobody validated."""

    async def test_confidence_is_derived_from_backtested_error(self):
        out = await forecast([deal("100000")])
        # MAPE 0.20 -> 0.80 base, full coverage, current period.
        assert out["confidence"] == pytest.approx(0.80, abs=0.001)

    async def test_a_worse_backtest_lowers_confidence(self, monkeypatch):
        monkeypatch.setattr(
            forecast_model,
            "_artifact_cache",
            {
                "calibration": CALIBRATION,
                "metrics": {"backtest": {"weighted_pipeline": {"mape": 0.50}}},
            },
        )
        out = await forecast([deal("100000")])
        assert out["confidence"] == pytest.approx(0.50, abs=0.001)

    async def test_no_calibration_means_low_confidence_and_a_warning(self, monkeypatch):
        """A fresh clone has no artifacts — it must still forecast, but must
        not present guessed weights as measured ones."""

        monkeypatch.setattr(
            forecast_model, "_artifact_cache", {"calibration": None, "metrics": {}}
        )
        out = await forecast([deal("100000")])
        assert out["calibration_source"] == "default"
        assert out["confidence"] <= UNCALIBRATED_CONFIDENCE
        assert any("untrained defaults" in w for w in out["warnings"])

    async def test_missing_amounts_reduce_confidence(self):
        full = await forecast([deal("100000")])
        partial = await forecast([deal("100000"), deal(None, id="d2")])
        assert partial["confidence"] < full["confidence"]

    async def test_a_further_horizon_reduces_confidence(self):
        near = await forecast([deal("100000")], as_of=datetime(2026, 8, 5, tzinfo=UTC))
        far = await forecast([deal("100000")], as_of=datetime(2026, 5, 5, tzinfo=UTC))
        assert far["confidence"] < near["confidence"]
        assert far["breakdown"]["horizon_periods"] == 3

    async def test_thin_stage_support_reduces_confidence(self, monkeypatch):
        monkeypatch.setattr(
            forecast_model,
            "_artifact_cache",
            {
                "calibration": {
                    "rates": CALIBRATION["rates"],
                    "support": {**CALIBRATION["support"], "proposal_sent": 3},
                },
                "metrics": METRICS,
            },
        )
        out = await forecast([deal("100000", stage="proposal_sent")])
        assert out["confidence"] < 0.80

    async def test_unused_stages_do_not_drag_confidence_down(self, monkeypatch):
        """The training CRM has no `demo_scheduled` analogue, so its support is
        always zero. A tenant with no deals in that stage must not be penalised
        for a rate their forecast never touched."""

        monkeypatch.setattr(
            forecast_model,
            "_artifact_cache",
            {
                "calibration": {
                    "rates": CALIBRATION["rates"],
                    "support": {**CALIBRATION["support"], "demo_scheduled": 0},
                },
                "metrics": METRICS,
            },
        )
        out = await forecast([deal("100000", stage="proposal_sent")])
        assert out["confidence"] == pytest.approx(0.80, abs=0.001)

    async def test_confidence_is_capped(self, monkeypatch):
        monkeypatch.setattr(
            forecast_model,
            "_artifact_cache",
            {
                "calibration": CALIBRATION,
                "metrics": {"backtest": {"weighted_pipeline": {"mape": 0.0}}},
            },
        )
        assert (await forecast([deal("100000")]))["confidence"] <= MAX_CONFIDENCE


class TestBreakdown:
    async def test_top_deals_answers_which_deals_will_close(self):
        """The brief's own question 3 — something an aggregate monthly
        regression structurally cannot answer."""

        out = await forecast(
            [
                deal("10000", stage="negotiation", id="small", name="Small"),
                deal("900000", stage="proposal_sent", id="big", name="Big"),
            ]
        )
        assert [d["name"] for d in out["breakdown"]["top_deals"]][0] == "Big"

    async def test_stage_rollup_totals_match_the_forecast(self):
        out = await forecast(
            [
                deal("100000", stage="proposal_sent", id="a"),
                deal("200000", stage="negotiation", id="b"),
            ]
        )
        rolled = sum(Decimal(row["expected_value"]) for row in out["breakdown"]["by_stage"])
        assert rolled == Decimal(out["weighted_pipeline"])

    async def test_trend_compares_against_the_last_completed_period(self):
        out = await forecast(
            [deal("200000", stage="proposal_sent")],
            history=[{"period": "2026-07", "won_revenue": "50000"}],
        )
        assert out["breakdown"]["trend"]["previous_period"] == "2026-07"
        assert out["breakdown"]["trend"]["change_pct"] == 100.0

    async def test_no_history_means_no_invented_trend(self):
        out = await forecast([deal("100000")])
        assert out["breakdown"]["trend"]["change_pct"] is None

    async def test_model_version_and_explanation_are_reported(self):
        out = await forecast([deal("100000")])
        assert out["model_version"] == MODEL_VERSION
        assert "already won" in out["explanation"]
        assert "not a probability" in out["explanation"]


class TestCalibrationHelpers:
    def test_rescaling_preserves_stage_ordering(self):
        counts = {"new": 10, "qualified": 10, "proposal_sent": 10, "negotiation": 10}
        rates = rescale_rates(0.30, counts)
        assert rates["new"] < rates["qualified"] < rates["proposal_sent"] < rates["negotiation"]

    def test_rescaling_moves_the_level_onto_the_measured_rate(self):
        counts = {"new": 1, "qualified": 1, "proposal_sent": 1, "negotiation": 1}
        rates = rescale_rates(0.20, counts)
        open_stages = [s for s in rates if s not in features.CLOSED_STAGES]
        assert sum(rates[s] for s in open_stages) / len(open_stages) == pytest.approx(0.20, abs=0.01)

    def test_win_rate_is_point_in_time(self):
        """A backtest for August must not know how August's deals turned out."""

        deals = [
            {"is_closed": 1, "is_won": 1, "actual_close_date": "2026-07-10"},
            {"is_closed": 1, "is_won": 0, "actual_close_date": "2026-07-20"},
            {"is_closed": 1, "is_won": 1, "actual_close_date": "2026-08-02"},
        ]
        rate, support = measured_win_rate(deals, before="2026-08")
        assert (rate, support) == (0.5, 2)

    def test_regression_metrics(self):
        metrics = regression_metrics([100.0, 200.0], [100.0, 100.0])
        assert metrics["mae"] == 50.0
        assert metrics["mape"] == 0.5


class TestPeriodBounds:
    def test_month(self):
        start, end = forecast_service.period_bounds("2026-08")
        assert (start.month, end.month) == (8, 9)

    def test_december_rolls_the_year(self):
        start, end = forecast_service.period_bounds("2026-12")
        assert (end.year, end.month) == (2027, 1)

    def test_quarter(self):
        start, end = forecast_service.period_bounds("2026-Q3")
        assert (start.month, end.month) == (7, 10)

    def test_q4_rolls_the_year(self):
        _, end = forecast_service.period_bounds("2026-Q4")
        assert (end.year, end.month) == (2027, 1)

    @pytest.mark.parametrize("bad", ["2026-13", "2026-Q5", "August", "2026", ""])
    def test_malformed_periods_are_rejected(self, bad):
        from app.core.exceptions import ValidationError

        with pytest.raises(ValidationError):
            forecast_service.period_bounds(bad)


# ------------------------------------------------------------------ service


async def seed_deal(db, tenant, *, amount, currency="INR", stage=None, close="2026-08-20"):
    from app.models.deal import Deal, DealStage

    row = Deal(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        name="Opportunity",
        stage=stage or DealStage.PROPOSAL_SENT,
        amount=None if amount is None else Decimal(amount),
        currency=currency,
        expected_close_date=None if close is None else datetime.fromisoformat(f"{close}T00:00:00+00:00"),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def seed_won(db, tenant, *, amount, currency="INR", closed_at="2026-08-10"):
    from app.models.deal import Deal, DealStage
    from app.models.feedback import DealOutcome, Outcome

    row = Deal(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        name="Won deal",
        stage=DealStage.CLOSED_WON,
        amount=Decimal(amount),
        currency=currency,
    )
    db.add(row)
    await db.flush()
    db.add(
        DealOutcome(
            company_id=tenant.company_id,
            deal_id=row.id,
            lead_id=tenant.lead_id,
            outcome=Outcome.WON,
            closed_at=datetime.fromisoformat(f"{closed_at}T00:00:00+00:00"),
        )
    )
    await db.commit()
    return row


class TestForecastService:
    async def test_one_forecast_row_per_currency(self, db, tenant):
        """Summing an INR deal and a USD deal produces a figure that is not
        money, and there is no FX source in this service."""

        await seed_deal(db, tenant, amount="100000", currency="INR")
        await seed_deal(db, tenant, amount="2000", currency="USD")

        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert {r.currency for r in rows} == {"INR", "USD"}
        assert all(isinstance(r.predicted_revenue, Decimal) for r in rows)

    async def test_committed_revenue_comes_from_the_outcome_date(self, db, tenant):
        """`Deal.stage` says a deal is won; only `DealOutcome.closed_at` says
        when — a forecast for August must count August's wins."""

        await seed_won(db, tenant, amount="500000", closed_at="2026-08-10")
        await seed_won(db, tenant, amount="900000", closed_at="2026-06-10")

        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert rows[0].committed_revenue == Decimal("500000.00")

    async def test_archived_deals_are_excluded(self, db, tenant):
        row = await seed_deal(db, tenant, amount="100000")
        row.archived_at = datetime.now(UTC)
        await db.commit()

        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert rows[0].weighted_pipeline == Decimal("0.00")

    async def test_deals_on_an_archived_lead_are_excluded(self, db, tenant):
        """Archiving a lead must remove its deals from every view — a forecast
        counting them reports revenue from accounts nobody is working."""

        from app.models.lead import Lead

        await seed_deal(db, tenant, amount="100000")
        lead = await db.get(Lead, tenant.lead_id)
        lead.archived_at = datetime.now(UTC)
        await db.commit()

        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert rows[0].weighted_pipeline == Decimal("0.00")

    async def test_another_tenants_pipeline_is_invisible(self, db, tenant, other_tenant):
        await seed_deal(db, other_tenant, amount="9999999")
        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert rows[0].weighted_pipeline == Decimal("0.00")

    async def test_an_empty_workspace_still_produces_a_row(self, db, tenant):
        rows = await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        assert len(rows) == 1
        assert rows[0].predicted_revenue == Decimal("0.00")

    async def test_forecasts_are_append_only(self, db, tenant):
        await seed_deal(db, tenant, amount="100000")
        for _ in range(2):
            await forecast_service.generate_forecast(
                db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
            )
        count = (await db.execute(text("SELECT count(*) FROM revenue_forecasts"))).scalar()
        assert count == 2

        latest = await forecast_service.latest_forecasts(db, company_id=tenant.company_id)
        assert len(latest) == 1, "a manager must not see the same period twice"


# ---------------------------------------------------------------------- API


class _FakeTask:
    def __init__(self):
        self.calls: list[tuple] = []

    def delay(self, *args):
        self.calls.append(args)


@pytest.fixture
def fake_task(monkeypatch):
    task = _FakeTask()
    monkeypatch.setattr("app.routers.ai.run_revenue_forecast", task)
    return task


class TestForecastEndpoints:
    def test_run_dispatches_a_job(self, client, tenant, fake_task):
        r = client.post(
            f"{V1}/ai/forecast/run",
            json={"forecast_period": "2026-08"},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 202, r.text
        assert fake_task.calls[0][1] == "2026-08"

    def test_a_malformed_period_is_rejected_before_a_job_is_created(self, client, tenant, fake_task):
        """A typo should be a 422 the caller sees, not a job that fails
        silently and leaves a spinner nobody can clear."""

        r = client.post(
            f"{V1}/ai/forecast/run",
            json={"forecast_period": "August"},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "INVALID_FORECAST_PERIOD"
        assert not fake_task.calls

    def test_omitting_the_period_forecasts_the_current_month(self, client, tenant, fake_task):
        r = client.post(f"{V1}/ai/forecast/run", json={}, headers=tenant.headers("sales_manager"))
        assert r.status_code == 202
        assert fake_task.calls[0][1] is None

    def test_sales_executives_cannot_see_the_company_forecast(self, client, tenant):
        """Leadership KPI. The service deliberately does not narrow the
        pipeline to one rep, so access is restricted by who may ask."""

        assert (
            client.get(f"{V1}/ai/forecast", headers=tenant.headers("sales_executive")).status_code
            == 403
        )

    async def test_get_returns_the_latest_per_period_and_currency(self, client, db, tenant):
        await seed_deal(db, tenant, amount="100000", currency="INR")
        for _ in range(2):
            await forecast_service.generate_forecast(
                db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
            )

        headers = tenant.headers("sales_manager")
        current = client.get(f"{V1}/ai/forecast", headers=headers).json()["data"]
        full = client.get(f"{V1}/ai/forecast?history=true", headers=headers).json()["data"]
        assert len(current) == 1
        assert len(full) == 2
        assert current[0]["currency"] == "INR"
        assert current[0]["explanation"]
        assert current[0]["breakdown"]["by_stage"]

    async def test_money_survives_the_api_boundary_exactly(self, client, db, tenant):
        await seed_deal(db, tenant, amount="0.10", currency="INR", stage=None)
        await forecast_service.generate_forecast(
            db, company_id=tenant.company_id, period="2026-08", as_of=AS_OF
        )
        data = client.get(f"{V1}/ai/forecast", headers=tenant.headers("sales_manager")).json()[
            "data"
        ][0]
        assert Decimal(str(data["predicted_revenue"])) == Decimal(
            str(data["committed_revenue"])
        ) + Decimal(str(data["weighted_pipeline"]))

    async def test_cross_tenant_forecasts_are_not_returned(self, client, db, tenant, other_tenant):
        await forecast_service.generate_forecast(
            db, company_id=other_tenant.company_id, period="2026-08", as_of=AS_OF
        )
        data = client.get(f"{V1}/ai/forecast", headers=tenant.headers("sales_manager")).json()[
            "data"
        ]
        assert data == []


class TestOrchestrator:
    async def test_forecast_job_completes_with_the_result(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.services.ai_orchestrator import AIOrchestrator

        await seed_deal(db, tenant, amount="100000", currency="INR")
        job = Job(
            company_id=tenant.company_id,
            job_type="revenue_forecast",
            created_by_user_id=tenant.manager_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()

        await AIOrchestrator(db).generate_revenue_forecast(job=job, period="2026-08")
        assert job.status == JobStatus.COMPLETED
        assert job.result["forecast_period"] == "2026-08"
        assert job.result["forecasts"][0]["currency"] == "INR"

    async def test_agent_io_is_logged_without_a_lead(self, db, tenant):
        """A forecast is over the whole pipeline; forcing it to name a lead
        would misattribute a company-level output."""

        from app.models.job import Job, JobStatus
        from app.services.ai_orchestrator import AIOrchestrator

        job = Job(
            company_id=tenant.company_id, job_type="revenue_forecast", status=JobStatus.PENDING
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).generate_revenue_forecast(job=job, period="2026-08")

        rows = (
            await db.execute(
                text("SELECT agent_name, lead_id FROM ai_interaction_logs")
            )
        ).all()
        assert rows and rows[0][0] == "revenue_forecasting"
        assert rows[0][1] is None

    async def test_a_bad_period_fails_the_job_rather_than_raising(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.services.ai_orchestrator import AIOrchestrator

        job = Job(
            company_id=tenant.company_id, job_type="revenue_forecast", status=JobStatus.PENDING
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).generate_revenue_forecast(job=job, period="nonsense")
        assert job.status == JobStatus.FAILED
        assert job.error_message
