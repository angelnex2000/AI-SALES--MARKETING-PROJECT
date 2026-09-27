"""Supervisor planning, payload scoping, and the outreach workflow it drives.

Two rules under test:

  * The Supervisor **plans and does not perform** — so every branch of "should
    this step run?" is assertable without a database, a broker, or an LLM key.
  * Reuse is a correctness decision, not just a cost one. Skipping research
    that is fresh enough for ranking but not for a customer email is how a
    caching layer starts asserting things that are no longer true.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from agents.supervisor import planner
from agents.supervisor.agent import SupervisorAgent, UnknownWorkflowError
from agents.supervisor.workflow import (
    DAY,
    LEAD_INTELLIGENCE,
    OUTREACH_DRAFT,
    PayloadScopeError,
    scoped_payload,
)

V1 = "/api/v1"


def snapshot(age_days=None, *, exists=True, invalidated_after=None):
    if not exists:
        return {"research": {"exists": False}}
    return {
        "research": {
            "exists": True,
            "age_seconds": (age_days or 0) * DAY,
            "invalidated_after": invalidated_after,
        }
    }


def decisions(plan):
    return {step.step: step for step in plan.steps}


class TestPlanning:
    def test_missing_output_runs_the_step(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(exists=False))
        assert decisions(plan)["research"].action == planner.RUN
        assert "no stored research" in decisions(plan)["research"].reason

    def test_fresh_output_is_reused(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(age_days=2))
        step = decisions(plan)["research"]
        assert step.action == planner.REUSE
        assert step.reused_age_seconds == 2 * DAY

    def test_stale_output_re_runs(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(age_days=20))
        assert decisions(plan)["research"].action == planner.RUN
        assert "beyond this workflow" in decisions(plan)["research"].reason

    def test_staleness_tolerance_belongs_to_the_consumer(self):
        """The same 10-day-old report is fine for ranking a lead and not fine
        for writing "I noticed you recently expanded" — so the TTL is on the
        step, not on the agent."""

        ten_days = snapshot(age_days=10)
        assert decisions(planner.plan(LEAD_INTELLIGENCE, snapshot=ten_days))[
            "research"
        ].action == planner.REUSE
        assert decisions(planner.plan(OUTREACH_DRAFT, snapshot=ten_days))[
            "research"
        ].action == planner.RUN

    def test_force_overrides_reuse(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(age_days=1), force=True)
        assert decisions(plan)["research"].action == planner.RUN
        assert plan.forced is True

    def test_a_configuration_change_invalidates_a_result_that_is_not_yet_old(self):
        """Not old — wrong. A score computed against a profile the tenant has
        since edited scores the lead against something nobody uses."""

        plan = planner.plan(
            OUTREACH_DRAFT, snapshot=snapshot(age_days=1, invalidated_after=0.5 * DAY)
        )
        step = decisions(plan)["research"]
        assert step.action == planner.RUN
        assert "predates a configuration change" in step.reason

    def test_a_step_with_no_artifact_always_runs(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(age_days=1))
        for name in ("campaign", "rag", "outreach"):
            assert decisions(plan)[name].action == planner.RUN

    def test_a_result_with_no_timestamp_is_not_trusted(self):
        plan = planner.plan(
            OUTREACH_DRAFT, snapshot={"research": {"exists": True, "age_seconds": None}}
        )
        assert decisions(plan)["research"].action == planner.RUN

    def test_every_decision_carries_a_reason(self):
        plan = planner.plan(OUTREACH_DRAFT, snapshot=snapshot(age_days=1))
        assert all(step.reason for step in plan.steps)


class TestSupervisorAgent:
    async def test_it_returns_a_plan_not_a_result(self):
        out = await SupervisorAgent().run(
            {"workflow": "outreach_draft", "snapshot": snapshot(age_days=1)}
        )
        assert "plan" in out
        assert out["plan"]["reused"] == ["research"]
        assert out["ends_at"] == "gate_2_exec_approves_send"

    async def test_it_holds_no_database_handle_and_imports_no_agent(self):
        """"The Supervisor should orchestrate work, not perform it", taken
        literally: it cannot perform work because it has nothing to perform it
        with."""

        import agents.supervisor.agent as module

        source = module.__file__
        with open(source, encoding="utf-8") as handle:
            text_body = handle.read()
        assert "AsyncSession" not in text_body
        assert "ResearchAgent" not in text_body
        assert "select(" not in text_body

    async def test_reuse_provenance_reaches_the_explanation(self):
        """A draft written from six-day-old research is fine; a reader has to
        be able to discover that is what happened."""

        out = await SupervisorAgent().run(
            {"workflow": "outreach_draft", "snapshot": snapshot(age_days=6)}
        )
        assert "Reusing stored output" in out["explanation"]
        assert "days ago" in out["explanation"]

    async def test_an_unknown_workflow_is_rejected(self):
        with pytest.raises(UnknownWorkflowError):
            await SupervisorAgent().run({"workflow": "world_domination"})

    async def test_a_forced_plan_says_so(self):
        out = await SupervisorAgent().run(
            {"workflow": "outreach_draft", "snapshot": snapshot(age_days=1), "force": True}
        )
        assert "Forced refresh" in out["explanation"]


class TestPayloadScope:
    """Section 8 — each agent sees only the memory it needs. In this
    architecture agents cannot fetch anything, so scoping the payload *is* the
    permission model, and it is enforced rather than conventional."""

    def test_declared_keys_pass_through(self):
        step = OUTREACH_DRAFT.step("outreach")
        payload = scoped_payload(step, {"recipient": {}, "strategy": {}, "chunks": []})
        assert set(payload) == {"recipient", "strategy", "chunks"}

    def test_undeclared_context_is_an_error_not_a_silent_drop(self):
        """Dropping it quietly would turn a wiring mistake into an agent
        running on incomplete input — a bad answer instead of an error."""

        step = OUTREACH_DRAFT.step("outreach")
        with pytest.raises(PayloadScopeError, match="lead_score"):
            scoped_payload(step, {"recipient": {}, "lead_score": 91})

    def test_missing_declared_keys_are_allowed(self):
        step = OUTREACH_DRAFT.step("outreach")
        assert scoped_payload(step, {"recipient": {}}) == {"recipient": {}}

    def test_the_outreach_agent_never_sees_the_raw_lead_record(self):
        """It gets a recipient context with evidence and inference already
        separated — not the lead row it could read anything from."""

        assert "lead" not in OUTREACH_DRAFT.step("outreach").payload_scope

    def test_every_step_declares_a_scope(self):
        for flow in (LEAD_INTELLIGENCE, OUTREACH_DRAFT):
            for step in flow.steps:
                assert step.payload_scope, f"{flow.name}.{step.name} declares no scope"

    async def test_the_research_scope_matches_what_the_orchestrator_builds(self, db, tenant):
        """A declared scope that describes nothing the agent is handed is the
        same failure as an architecture map that has drifted — so it is checked
        against the real payload, not against a tidier version of it."""

        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        lead = await db.get(Lead, tenant.lead_id)
        built = await AIOrchestrator(db)._build_research_input(lead)
        declared = set(OUTREACH_DRAFT.step("research").payload_scope)
        assert set(built) == declared


class TestWorkflowShape:
    def test_the_outreach_workflow_ends_at_the_human_gate(self):
        assert OUTREACH_DRAFT.ends_at == "gate_2_exec_approves_send"

    def test_rag_is_optional_but_outreach_is_not(self):
        """Retrieval failing is not draft generation failing: the ungrounded
        prompt forbids specific claims, which beats no email at all. Outreach
        failing *is* fatal — there is no fallback draft."""

        assert OUTREACH_DRAFT.step("rag").optional is True
        assert OUTREACH_DRAFT.step("outreach").optional is False

    def test_outreach_research_tolerance_is_tighter_than_ranking(self):
        assert (
            OUTREACH_DRAFT.step("research").reuse_within_seconds
            < LEAD_INTELLIGENCE.step("research").reuse_within_seconds
        )


# ------------------------------------------------- the wired outreach path


FAKE_LLM = {"subject": "Quick question about telemedicine", "body": "Hi there, short note."}


def fake_openai():
    """Stands in for the provider so the workflow is testable without a key."""

    client = AsyncMock()
    client.chat.completions.create.return_value = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {"message": type("Msg", (), {"content": __import__("json").dumps(FAKE_LLM)})()},
                )()
            ]
        },
    )()
    return client


@contextmanager
def outreach_env():
    """Patch every provider this workflow touches.

    The embedding patch is not optional. `settings` is one shared object, so
    patching `OPENAI_API_KEY` for the Outreach Agent also switches it on for the
    embeddings module, and the RAG step then makes a **real HTTPS call** to
    OpenAI with a fake key — which took the suite from 68s to 152s and made it
    depend on the developer's network. Returning a vector exercises the
    realistic path instead: we could look, and nothing is indexed.
    """

    with patch("agents.outreach.providers.settings.LLM_PROVIDER", "openai"), patch(
        "agents.outreach.providers.settings.OPENAI_API_KEY", "test-key"
    ), patch("agents.outreach.providers.AsyncOpenAI", return_value=fake_openai()), patch(
        "agents.rag.retriever.embedding_model.embed_one",
        new=AsyncMock(return_value=[0.0] * 1536),
    ):
        yield


async def run_outreach(db, tenant, **kwargs):
    from app.models.job import Job, JobStatus
    from app.models.lead import Lead
    from app.services.ai_orchestrator import AIOrchestrator

    lead = await db.get(Lead, tenant.lead_id)
    job = Job(
        company_id=tenant.company_id,
        job_type="outreach_draft",
        lead_id=lead.id,
        created_by_user_id=tenant.exec_id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await AIOrchestrator(db).generate_outreach_draft(lead=lead, job=job, **kwargs)
    return job


class TestOutreachWorkflow:
    """Module 1 recorded this as the largest gap: Gate 2 was complete and
    tested but nothing produced a draft for it to gate."""

    async def test_a_draft_is_produced_and_lands_pending_approval(self, db, tenant):
        from app.models.outreach import DraftStatus

        with outreach_env():
            job = await run_outreach(db, tenant)

        assert job.status.value == "completed", job.error_message
        rows = (
            await db.execute(text("SELECT subject, status, ai_generated FROM email_drafts"))
        ).all()
        assert len(rows) == 1
        assert rows[0][1] == DraftStatus.PENDING_APPROVAL.value
        assert rows[0][2] == 1

    async def test_no_llm_means_no_draft(self, db, tenant):
        """A templated fallback is the generic email this feature replaces,
        relabelled as AI-personalised."""

        with patch("agents.outreach.providers.settings.LLM_PROVIDER", "auto"), patch(
            "agents.outreach.providers.settings.OPENAI_API_KEY", ""
        ), patch("agents.outreach.providers.settings.ANTHROPIC_API_KEY", ""):
            job = await run_outreach(db, tenant)

        assert job.status.value == "failed"
        assert "unavailable" in job.error_message.lower()
        count = (await db.execute(text("SELECT count(*) FROM email_drafts"))).scalar()
        assert count == 0, "a failed generation must not leave a draft behind"

    async def test_the_whole_agent_chain_is_logged(self, db, tenant):
        with outreach_env():
            await run_outreach(db, tenant)

        logged = [
            row[0]
            for row in (
                await db.execute(
                    text("SELECT agent_name FROM ai_interaction_logs ORDER BY created_at, rowid")
                )
            ).all()
        ]
        # Two campaign rows on purpose: the query pass that feeds RAG, then the
        # authoritative pass computed from what RAG returned. Distinct step
        # names keep them readable as two different things.
        assert logged == ["research", "campaign", "rag", "campaign", "outreach"]

        steps = [
            row[0]
            for row in (
                await db.execute(
                    text("SELECT step FROM ai_interaction_logs ORDER BY created_at, rowid")
                )
            ).all()
        ]
        assert steps == ["research", "campaign_query", "rag", "campaign", "outreach"]

    async def test_fresh_research_is_reused_rather_than_re_run(self, db, tenant):
        """Section 7's whole point — and the saving is real, since research is
        the slowest step in the chain."""

        with outreach_env():
            await run_outreach(db, tenant)
            await run_outreach(db, tenant)

        reports = (await db.execute(text("SELECT count(*) FROM ai_research_reports"))).scalar()
        assert reports == 1, "the second run should have reused the first report"

    async def test_stale_research_is_refreshed(self, db, tenant):
        from sqlalchemy import select

        from app.models.lead import ResearchReport

        with outreach_env():
            await run_outreach(db, tenant)
            report = (await db.execute(select(ResearchReport))).scalars().first()
            report.created_at = datetime.now(UTC) - timedelta(days=30)
            await db.commit()

            await run_outreach(db, tenant)

        reports = (await db.execute(text("SELECT count(*) FROM ai_research_reports"))).scalar()
        assert reports == 2

    async def test_reused_research_age_is_disclosed_on_the_draft(self, db, tenant):
        """"I noticed you recently expanded" is a claim about *when*. The
        reviewer must be able to see how old the source was."""

        with outreach_env():
            await run_outreach(db, tenant)
            await run_outreach(db, tenant)

        explanations = [
            row[0]
            for row in (
                await db.execute(text("SELECT explanation FROM email_drafts ORDER BY created_at"))
            ).all()
        ]
        assert "days old" in explanations[-1]
        assert "check any time-sensitive claim" in explanations[-1]

    async def test_provenance_columns_are_recorded(self, db, tenant):
        """A complaint about a claim in a sent email must be traceable to the
        exact model, prompt and documents that produced it."""

        with outreach_env():
            await run_outreach(db, tenant)

        row = (
            await db.execute(text("SELECT llm_model, prompt_version FROM email_drafts"))
        ).one()
        assert row[0] and row[1]

    async def test_an_ungrounded_draft_is_still_produced(self, db, tenant):
        """No tenant has indexed content, so RAG returns nothing. A generic
        email is worse than a grounded one; an invented customer outcome is
        worse than both."""

        with outreach_env():
            job = await run_outreach(db, tenant)

        assert job.status.value == "completed"
        assert job.result["grounded"] is False


class TestGenerateEndpoint:
    class _Task:
        def __init__(self):
            self.calls: list[tuple] = []

        def delay(self, *args):
            self.calls.append(args)

    async def test_generate_dispatches_instead_of_creating_a_dead_job(
        self, client, db, tenant, monkeypatch
    ):
        task = self._Task()
        monkeypatch.setattr("app.routers.outreach.run_outreach_draft", task)
        r = client.post(
            f"{V1}/outreach/generate",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 202, r.text
        assert task.calls, "the job must reach the worker"
        assert task.calls[0][1] == str(tenant.lead_id)

    async def test_double_click_does_not_queue_two_drafts(self, client, db, tenant, monkeypatch):
        """Two drafts for the same lead in the approval queue, and twice the
        LLM spend."""

        task = self._Task()
        monkeypatch.setattr("app.routers.outreach.run_outreach_draft", task)
        body = {"lead_id": str(tenant.lead_id)}
        headers = tenant.headers("sales_executive")
        client.post(f"{V1}/outreach/generate", json=body, headers=headers)
        second = client.post(f"{V1}/outreach/generate", json=body, headers=headers)
        assert "already being generated" in second.json()["message"]
        assert len(task.calls) == 1

    async def test_marketing_may_draft(self, client, db, tenant, monkeypatch):
        monkeypatch.setattr("app.routers.outreach.run_outreach_draft", self._Task())
        r = client.post(
            f"{V1}/outreach/generate",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("marketing"),
        )
        assert r.status_code == 202

    async def test_admin_may_not_draft(self, client, db, tenant):
        r = client.post(
            f"{V1}/outreach/generate",
            json={"lead_id": str(tenant.lead_id)},
            headers=tenant.headers("admin"),
        )
        assert r.status_code == 403

    async def test_cross_tenant_lead_is_404(self, client, db, tenant, other_tenant):
        r = client.post(
            f"{V1}/outreach/generate",
            json={"lead_id": str(other_tenant.lead_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 404


class TestGateStillHolds:
    """The workflow now produces drafts. Gate 2 must still be the only way one
    reaches a customer."""

    async def test_a_generated_draft_cannot_be_sent_without_approval(self, client, db, tenant):
        with outreach_env():
            job = await run_outreach(db, tenant)

        draft_id = job.result["draft_id"]
        r = client.post(
            f"{V1}/outreach/drafts/{draft_id}/send", headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "DRAFT_NOT_APPROVED"

    async def test_the_normal_path_still_works(self, client, db, tenant):
        with outreach_env():
            job = await run_outreach(db, tenant)

        draft_id = job.result["draft_id"]
        headers = tenant.headers("sales_executive")
        assert (
            client.post(f"{V1}/outreach/drafts/{draft_id}/approve", headers=headers).status_code
            == 200
        )
        assert (
            client.post(f"{V1}/outreach/drafts/{draft_id}/send", headers=headers).status_code == 200
        )
