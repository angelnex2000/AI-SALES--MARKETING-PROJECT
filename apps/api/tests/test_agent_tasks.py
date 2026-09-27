"""Agent task records, retry classification, and run correlation.

The gap this module closed: `ai_interaction_logs` was written *after* an agent
returned, at nine separate call sites, so a raising agent left nothing behind.
The one table built for "auditing what an agent was actually given" was blind
to the failure case — the only case anyone opens it for.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text

from agents.base import BaseAgent
from agents.supervisor import failures
from app.models.ai_log import AgentTaskStatus, AIInteractionLog
from app.models.job import Job, JobStatus
from app.models.lead import Lead
from app.services.ai_orchestrator import AIOrchestrator

V1 = "/api/v1"


class Boom(BaseAgent):
    """An agent that fails a given number of times, then succeeds."""

    def __init__(self, exc: BaseException, fail_times: int = 99):
        self.exc = exc
        self.fail_times = fail_times
        self.calls = 0

    async def run(self, input_data):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return {"model_version": "v1", "ok": True}


class Fine(BaseAgent):
    async def run(self, input_data):
        return {"model_version": "v9", "answer": 42}


async def make_job(db, tenant) -> Job:
    job = Job(
        company_id=tenant.company_id,
        job_type="lead_intelligence",
        lead_id=tenant.lead_id,
        created_by_user_id=tenant.exec_id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    return job


async def rows(db) -> list[AIInteractionLog]:
    return list(
        (await db.execute(select(AIInteractionLog).order_by(AIInteractionLog.started_at)))
        .scalars()
        .all()
    )


# ------------------------------------------------------ failure classification


class TestFailureClassification:
    """Deny by default: retry only what is positively identified as transient.
    A permanent failure retried is waste with no upside; a transient one not
    retried leaves a job the user can re-trigger."""

    @pytest.mark.parametrize(
        "exc",
        [TimeoutError("slow"), ConnectionError("reset"), ConnectionResetError("peer")],
    )
    def test_network_errors_are_transient(self, exc):
        assert failures.is_transient(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [ValueError("bad input"), KeyError("missing"), RuntimeError("no api key")],
    )
    def test_everything_else_is_permanent(self, exc):
        assert failures.is_transient(exc) is False

    def test_a_wrapped_transient_cause_is_found(self):
        """The Outreach Agent raises `OutreachUnavailableError` *from* whatever
        the provider raised, so the wrapper type says nothing and only the
        cause does."""

        try:
            try:
                raise TimeoutError("provider timed out")
            except TimeoutError as inner:
                raise RuntimeError("outreach unavailable") from inner
        except RuntimeError as outer:
            assert failures.is_transient(outer) is True

    def test_a_missing_api_key_is_not_retried(self):
        """Raised with no cause. Three attempts would be three round trips to
        learn what the first one said."""

        exc = RuntimeError("OPENAI_API_KEY is not set")
        assert failures.is_transient(exc) is False
        assert failures.should_retry(exc, attempt=1) is False

    def test_an_exhausted_quota_is_permanent_despite_being_a_429(self):
        """The bug a real exhausted key surfaced. Providers reuse both the 429
        status and the `RateLimitError` type for "too many requests this
        minute" (clears itself) and "this account has no credits" (never
        clears). Retrying the second costs three round trips and five seconds
        of backoff on every job to learn what attempt one already said."""

        class RateLimitError(Exception):
            code = "credit_balance_exhausted"
            body = {"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}}

        exc = RateLimitError("You have no credits remaining")
        assert failures.is_transient(exc) is False
        assert failures.should_retry(exc, attempt=1) is False

    def test_a_genuine_rate_limit_is_still_retried(self):
        """The fix must not make every 429 permanent — that would fail jobs
        that a one-second wait would have completed."""

        class RateLimitError(Exception):
            code = "rate_limit_exceeded"

        assert failures.is_transient(RateLimitError("slow down")) is True

    def test_a_permanent_code_wins_over_a_transient_type_name(self):
        """Checked first, so the type name cannot override the provider's own
        structured verdict."""

        class TimeoutError_(Exception):  # a name in TRANSIENT_TYPE_NAMES
            code = "invalid_api_key"

        TimeoutError_.__name__ = "TimeoutError"
        assert failures.is_transient(TimeoutError_("x")) is False

    def test_permanent_codes_are_matched_structurally_not_by_message(self):
        """Provider prose gets reworded; `error.code` is part of their API."""

        class Wrapped(Exception):
            pass

        assert failures.is_transient(Wrapped("you have no credits remaining")) is False, (
            "an unknown exception is permanent by default, not because of its wording"
        )

    def test_retries_are_bounded(self):
        exc = TimeoutError("slow")
        assert failures.should_retry(exc, attempt=failures.MAX_ATTEMPTS) is False

    def test_the_description_names_the_cause(self):
        """"OutreachUnavailableError: connection error" alone does not say
        whether the fix is a config change or a retry."""

        try:
            try:
                raise ConnectionError("dns failure")
            except ConnectionError as inner:
                raise RuntimeError("wrapped") from inner
        except RuntimeError as outer:
            described = failures.describe(outer)
        assert "RuntimeError" in described
        assert "ConnectionError" in described
        assert "dns failure" in described

    def test_backoff_grows_and_the_first_attempt_does_not_wait(self):
        assert failures.delay_before(1) == 0.0
        assert failures.delay_before(2) < failures.delay_before(3)


# ------------------------------------------------------------- task recording


class TestTaskRecording:
    async def test_a_successful_call_records_the_full_contract(self, db, tenant):
        job = await make_job(db, tenant)
        run_id = __import__("uuid").uuid4()
        await AIOrchestrator(db).run_agent(
            Fine(),
            {"hello": "world"},
            company_id=tenant.company_id,
            lead_id=tenant.lead_id,
            run_id=run_id,
            workflow_name="lead_intelligence",
            job=job,
            step="research",
            agent_name="research",
        )
        await db.commit()

        [row] = await rows(db)
        # The module brief's section 8 list, in full.
        assert row.run_id == run_id
        assert row.agent_name == "research"
        assert row.step == "research"
        assert row.input_payload == {"hello": "world"}
        assert row.output_payload["answer"] == 42
        assert row.status == AgentTaskStatus.COMPLETED
        assert row.error is None
        assert row.started_at and row.completed_at
        assert row.duration_ms is not None
        assert row.model_version == "v9"

    async def test_a_failing_agent_is_recorded_rather_than_leaving_silence(self, db, tenant):
        """The whole point of the module. Before this, all that survived a
        failure was a string on the Job row — no record of which step died,
        what it was handed, or how long it ran."""

        job = await make_job(db, tenant)
        with pytest.raises(ValueError):
            await AIOrchestrator(db).run_agent(
                Boom(ValueError("agent exploded")),
                {"lead": "acme"},
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                job=job,
                step="research",
                agent_name="research",
            )

        [row] = await rows(db)
        assert row.status == AgentTaskStatus.FAILED
        assert "agent exploded" in row.error
        assert row.output_payload is None, "a failed attempt has no output"
        assert row.input_payload == {"lead": "acme"}
        assert row.duration_ms is not None

    async def test_the_failure_record_survives_the_workflow_rolling_back(self, db, tenant):
        """An uncommitted failure row would be rolled back along with the
        workflow that is about to raise — losing the only evidence."""

        job = await make_job(db, tenant)
        with pytest.raises(ValueError):
            await AIOrchestrator(db).run_agent(
                Boom(ValueError("boom")),
                {},
                company_id=tenant.company_id,
                job=job,
                step="research",
                agent_name="research",
            )
        await db.rollback()

        count = (await db.execute(text("SELECT count(*) FROM ai_interaction_logs"))).scalar()
        assert count == 1

    async def test_output_that_is_not_json_serialisable_still_records(self, db, tenant):
        """Forecast payloads carry `Decimal` and `datetime`. Losing the audit
        row because of a type the JSON column cannot take would defeat the
        point of recording it."""

        from decimal import Decimal

        class Money(BaseAgent):
            async def run(self, input_data):
                return {"model_version": "v1", "amount": Decimal("10.50")}

        job = await make_job(db, tenant)
        await AIOrchestrator(db).run_agent(
            Money(),
            {"when": datetime.now(UTC)},
            company_id=tenant.company_id,
            job=job,
            step="revenue_forecasting",
            agent_name="revenue_forecasting",
        )
        await db.commit()

        [row] = await rows(db)
        assert row.output_payload["amount"] == "10.50"


class TestRetry:
    async def test_a_transient_failure_is_retried_and_can_succeed(self, db, tenant, monkeypatch):
        monkeypatch.setattr(failures, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
        job = await make_job(db, tenant)
        agent = Boom(TimeoutError("slow"), fail_times=1)

        result = await AIOrchestrator(db).run_agent(
            agent,
            {},
            company_id=tenant.company_id,
            job=job,
            step="research",
            agent_name="research",
        )
        await db.commit()

        assert result["ok"] is True
        assert agent.calls == 2

    async def test_every_attempt_gets_its_own_row(self, db, tenant, monkeypatch):
        """A task that succeeded on the third try is otherwise indistinguishable
        from one that succeeded immediately — the difference being a provider
        degrading under load."""

        monkeypatch.setattr(failures, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
        job = await make_job(db, tenant)
        await AIOrchestrator(db).run_agent(
            Boom(TimeoutError("slow"), fail_times=1),
            {},
            company_id=tenant.company_id,
            job=job,
            step="research",
            agent_name="research",
        )
        await db.commit()

        recorded = await rows(db)
        assert [(r.attempt, r.status) for r in recorded] == [
            (1, AgentTaskStatus.FAILED),
            (2, AgentTaskStatus.COMPLETED),
        ]

    async def test_a_permanent_failure_is_not_retried(self, db, tenant):
        job = await make_job(db, tenant)
        agent = Boom(ValueError("bad config"))
        with pytest.raises(ValueError):
            await AIOrchestrator(db).run_agent(
                agent,
                {},
                company_id=tenant.company_id,
                job=job,
                step="research",
                agent_name="research",
            )
        assert agent.calls == 1, "retrying a permanent failure is waste with no upside"

    async def test_retries_give_up_and_re_raise(self, db, tenant, monkeypatch):
        monkeypatch.setattr(failures, "RETRY_DELAYS_SECONDS", (0.0, 0.0))
        job = await make_job(db, tenant)
        agent = Boom(TimeoutError("always slow"))
        with pytest.raises(TimeoutError):
            await AIOrchestrator(db).run_agent(
                agent,
                {},
                company_id=tenant.company_id,
                job=job,
                step="research",
                agent_name="research",
            )
        assert agent.calls == failures.MAX_ATTEMPTS


class TestRunCorrelation:
    async def test_one_run_id_ties_a_whole_workflow_together(self, db, tenant):
        """Without it, "show me everything that happened in that run" is a
        guess from timestamps, and two concurrent runs on the same lead are
        indistinguishable."""

        lead = await db.get(Lead, tenant.lead_id)
        job = await make_job(db, tenant)
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        recorded = await rows(db)
        assert len(recorded) == 4
        assert len({r.run_id for r in recorded}) == 1
        assert all(r.run_id is not None for r in recorded)
        assert all(r.job_id == job.id for r in recorded)
        assert [r.workflow for r in recorded] == ["lead_intelligence"] * 4

    async def test_two_runs_on_one_lead_stay_distinguishable(self, db, tenant):
        lead = await db.get(Lead, tenant.lead_id)
        for _ in range(2):
            job = await make_job(db, tenant)
            await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        recorded = await rows(db)
        assert len({r.run_id for r in recorded}) == 2

    async def test_timings_are_recorded_per_step(self, db, tenant):
        lead = await db.get(Lead, tenant.lead_id)
        job = await make_job(db, tenant)
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        for row in await rows(db):
            assert row.started_at is not None
            assert row.completed_at >= row.started_at
            assert row.duration_ms >= 0


class TestInteractionsEndpoint:
    async def test_a_run_can_be_replayed_in_order(self, client, db, tenant):
        lead = await db.get(Lead, tenant.lead_id)
        job = await make_job(db, tenant)
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)
        run_id = (await rows(db))[0].run_id

        data = client.get(
            f"{V1}/ai/interactions?run_id={run_id}", headers=tenant.headers("admin")
        ).json()["data"]
        assert [row["step"] for row in data] == [
            "research",
            "buying_signals",
            "icp_matching",
            "lead_scoring",
        ]

    async def test_failed_tasks_can_be_filtered_for(self, client, db, tenant):
        """Finding what broke without reading every successful call around it."""

        job = await make_job(db, tenant)
        with pytest.raises(ValueError):
            await AIOrchestrator(db).run_agent(
                Boom(ValueError("nope")),
                {},
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                job=job,
                step="research",
                agent_name="research",
            )

        data = client.get(
            f"{V1}/ai/interactions?task_status=failed", headers=tenant.headers("admin")
        ).json()["data"]
        assert len(data) == 1
        assert data[0]["error"]
        assert data[0]["output_payload"] is None

    async def test_still_admin_only(self, client, tenant):
        assert (
            client.get(f"{V1}/ai/interactions", headers=tenant.headers("sales_manager")).status_code
            == 403
        )

    async def test_cross_tenant_tasks_are_not_returned(self, client, db, tenant, other_tenant):
        lead = await db.get(Lead, other_tenant.lead_id)
        job = Job(
            company_id=other_tenant.company_id,
            job_type="lead_intelligence",
            lead_id=lead.id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        data = client.get(f"{V1}/ai/interactions", headers=tenant.headers("admin")).json()["data"]
        assert data == []
