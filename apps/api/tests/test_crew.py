"""CrewAI skeleton — the guard, the wiring, and the invariants the crew must
not be able to break.

`crewai` cannot currently be installed alongside this application (see
`requirements-crewai.txt` for the measured conflict), so the tests that need it
are marked `crewai` and skip. Everything that does *not* need it — the import
guard, the endpoint's 503, the crew/gate structure, and the rule that the
Crew's narration is never the source of truth — runs either way.
"""

import inspect

import pytest

from agents.crew import (
    CREWAI_INSTALL_HINT,
    CrewUnavailableError,
    crewai_available,
    require_crewai,
)

V1 = "/api/v1"

needs_crewai = pytest.mark.skipif(
    not crewai_available(), reason="crewai is not installable alongside this app — see requirements-crewai.txt"
)


class TestOptionalDependencyGuard:
    """The application must boot without crewai. A hard import at module level
    would take every route down over an optional extra."""

    def test_the_app_imports_without_crewai(self):
        from app.main import app

        assert app is not None

    def test_availability_is_reported_honestly(self):
        assert isinstance(crewai_available(), bool)

    def test_requiring_it_when_absent_says_what_to_install(self):
        if crewai_available():
            pytest.skip("crewai is importable here")
        with pytest.raises(CrewUnavailableError) as excinfo:
            require_crewai()
        assert "requirements-crewai.txt" in str(excinfo.value)

    def test_the_skeleton_modules_import_without_crewai(self):
        """Guarded imports are the point — these must be readable, and
        testable, in an environment that cannot install the dependency."""

        import agents.crew.agents as agents_mod
        import agents.crew.crew as crew_mod
        import agents.crew.tools as tools_mod

        assert callable(crew_mod.build_lead_intelligence_crew)
        assert callable(agents_mod.create_research_agent)
        assert callable(tools_mod.build_tools)

    def test_crewai_is_not_in_the_main_requirements(self):
        """Installing it into the app environment breaks FastAPI at import."""

        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        main = (root / "requirements.txt").read_text(encoding="utf-8").lower()
        assert "crewai" not in main
        assert (root / "requirements-crewai.txt").exists()


class TestEndpoint:
    def test_crew_run_is_503_when_the_dependency_is_absent(self, client, tenant):
        """503, not 500: the request was valid and the capability is missing."""

        if crewai_available():
            pytest.skip("crewai is importable here")
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/crew-run",
            json={"crew": "lead_intelligence"},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 503
        assert r.json()["error_code"] == "CREWAI_NOT_INSTALLED"
        assert "requirements-crewai.txt" in r.json()["message"]

    def test_the_catchall_does_not_shadow_crew_run(self, client, tenant):
        """`/leads/{id}/{agent}` is declared after it; declared before, it
        would swallow `crew-run` and report 'Unknown agent'."""

        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/crew-run",
            headers=tenant.headers("sales_manager"),
        )
        assert r.json().get("error_code") != "UNKNOWN_AGENT"

    def test_marketing_cannot_start_a_crew(self, client, tenant):
        r = client.post(
            f"{V1}/ai/leads/{tenant.lead_id}/crew-run",
            headers=tenant.headers("marketing"),
        )
        assert r.status_code == 403

    def test_cross_tenant_lead_is_not_reachable(self, client, tenant, other_tenant):
        """Isolation is checked before the crew is built — a crew's tools are
        bound to one lead's context precisely so a model cannot pick another."""

        r = client.post(
            f"{V1}/ai/leads/{other_tenant.lead_id}/crew-run",
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code in (404, 503)


class TestCrewStructure:
    """Structure assertions that hold without importing crewai — read from the
    source, because these are the properties that keep the gates real."""

    def _source(self, module) -> str:
        return inspect.getsource(module)

    def test_there_are_two_crews_split_at_the_human_gate(self):
        """The brief's single crew runs research → intelligence → outreach in
        one kickoff, which drafts an email for a lead no manager has assigned —
        automating straight through Gate 1."""

        from agents.crew.crew import CREWS

        assert set(CREWS) == {"lead_intelligence", "outreach_draft"}

    def test_the_intelligence_crew_stops_before_outreach(self):
        from agents.crew import crew as crew_mod

        source = self._source(crew_mod)
        intelligence = source.split("def build_lead_intelligence_crew")[1].split("def build_outreach_crew")[0]
        assert "create_outreach_agent" not in intelligence
        assert "Gate 1" in source or "gate" in source.lower()

    def test_delegation_is_disabled(self):
        """Module 1 settled that the order is fixed by data dependency, so
        letting a model reorder it can only make it wrong."""

        from agents.crew import agents as agents_mod

        assert "allow_delegation=False" in self._source(agents_mod)

    def test_the_process_is_sequential_not_hierarchical(self):
        """Hierarchical process puts a manager LLM in charge of delegation —
        the thing this architecture deliberately does not do."""

        from agents.crew import crew as crew_mod

        source = self._source(crew_mod)
        assert "Process.sequential" in source
        assert "Process.hierarchical" not in source

    def test_every_crew_agent_is_given_tools(self):
        """Without tools these are personas, and a 'Sales Intelligence Analyst'
        persona will happily invent a lead score that looks exactly like the
        trained model's."""

        from agents.crew import agents as agents_mod

        source = self._source(agents_mod)
        for factory in (
            "create_research_agent",
            "create_intelligence_agent",
            "create_campaign_agent",
            "create_outreach_agent",
        ):
            body = source.split(f"def {factory}")[1].split("\ndef ")[0]
            assert "tools=[" in body, f"{factory} builds an agent with no tools"

    def test_the_scoring_tool_is_declared_authoritative(self):
        from agents.crew import agents as agents_mod
        from agents.crew import tools as tools_mod

        assert "do not estimate" in self._source(agents_mod).lower()
        assert "authoritative" in self._source(tools_mod).lower()

    def test_narration_is_not_the_source_of_truth(self):
        """`kickoff()` returns whatever the last agent said; an LLM asked to
        report a score exactly will sometimes round it. Persisted values come
        from the tools' recorded state."""

        from app.services import crew_service

        source = self._source(crew_service)
        assert 'tools["state"]' in source
        assert '"narration"' in source

    def test_the_service_runs_kickoff_off_the_event_loop(self):
        """kickoff() is blocking and its tools open their own event loops;
        calling it inline would block the worker and then fail inside a running
        loop."""

        from app.services import crew_service

        assert "asyncio.to_thread(crew.kickoff)" in self._source(crew_service)

    def test_the_crew_cannot_send_an_email(self):
        """Gate 2 is not something a crew may pass. Nothing in the skeleton
        touches send_draft or SentEmail."""

        from agents.crew import agents as agents_mod
        from agents.crew import crew as crew_mod
        from agents.crew import tools as tools_mod
        from app.services import crew_service

        for module in (crew_mod, agents_mod, tools_mod, crew_service):
            source = self._source(module)
            assert "send_draft" not in source
            assert "SentEmail" not in source


class TestBackgroundExecution:
    """Section 9: agent workflows run in background jobs."""

    def test_a_celery_task_exists(self):
        from app.tasks import run_crew

        assert hasattr(run_crew, "delay")

    async def test_the_job_records_a_missing_dependency_as_a_failure(self, db, tenant):
        """Not an unhandled exception — the job row is the surface a polling
        frontend reads."""

        if crewai_available():
            pytest.skip("crewai is importable here")

        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services import crew_service

        lead = await db.get(Lead, tenant.lead_id)
        job = Job(
            company_id=tenant.company_id,
            job_type="crew_lead_intelligence",
            lead_id=lead.id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()

        await crew_service.run_crew(db, lead=lead, job=job)
        assert job.status == JobStatus.FAILED
        assert "crewai" in job.error_message.lower()
        assert job.completed_at is not None

    async def test_an_unknown_crew_fails_the_job_rather_than_raising(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services import crew_service

        lead = await db.get(Lead, tenant.lead_id)
        job = Job(
            company_id=tenant.company_id,
            job_type="crew_x",
            lead_id=lead.id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()

        await crew_service.run_crew(db, lead=lead, job=job, crew_name="nonsense")
        assert job.status == JobStatus.FAILED


class TestLeadContext:
    """The crew's tools see one lead's context and nothing else — there is no
    lead-id parameter for a model to get wrong."""

    async def test_context_carries_what_the_tools_need(self, db, tenant):
        from app.models.lead import Lead
        from app.services.crew_service import build_lead_context

        lead = await db.get(Lead, tenant.lead_id)
        context = await build_lead_context(db, lead)

        assert context["lead_id"] == str(tenant.lead_id)
        assert context["lead"]["name"] == lead.name
        assert "research_input" in context
        assert "scoring_features" in context
        assert context["recipient"]["company_name"] == lead.name

    async def test_context_includes_the_tenants_own_icp(self, db, tenant):
        """Shared agent code must never score a lead against another tenant's
        profile."""

        from app.models.company import Company
        from app.models.lead import Lead
        from app.services.crew_service import build_lead_context

        company = await db.get(Company, tenant.company_id)
        company.icp_config = {"target_industries": ["healthcare"]}
        await db.commit()

        lead = await db.get(Lead, tenant.lead_id)
        context = await build_lead_context(db, lead)
        assert context["icp_profile"] == {"target_industries": ["healthcare"]}


@needs_crewai
class TestWithCrewAIInstalled:
    """Only meaningful in an environment where the dependency resolves — see
    requirements-crewai.txt for why that is not this one."""

    async def test_tools_build(self, db, tenant):
        from agents.crew.tools import build_tools
        from app.models.lead import Lead
        from app.services.crew_service import build_lead_context

        lead = await db.get(Lead, tenant.lead_id)
        tools = build_tools(await build_lead_context(db, lead))
        assert {"research", "buying_signals", "icp", "score", "campaign", "outreach"} <= set(tools)

    async def test_crews_build(self, db, tenant):
        from agents.crew.crew import build_lead_intelligence_crew, build_outreach_crew
        from app.models.lead import Lead
        from app.services.crew_service import build_lead_context

        lead = await db.get(Lead, tenant.lead_id)
        context = await build_lead_context(db, lead)
        assert len(build_lead_intelligence_crew(context).tasks) == 2
        assert len(build_outreach_crew(context).tasks) == 3


def test_install_hint_names_the_extra_file():
    assert "requirements-crewai.txt" in CREWAI_INSTALL_HINT
