"""Research Agent: contract, evidence/inference separation, confidence, SSRF guard.

The agent takes a plain payload and returns a dict, so most of this needs no
database — which is the point of keeping agents independently testable.
"""

import pytest
from sqlalchemy import text

from agents.research import confidence
from agents.research.agent import MODEL_VERSION, ResearchAgent
from agents.research.schemas import ResearchInput, ResearchOutput
from agents.research.source_collector import UnsafeURLError, validate_fetchable_url

BASE = {
    "lead_id": "00000000-0000-0000-0000-000000000001",
    "company_name": "MedCare Hospital",
}


async def run(**overrides) -> dict:
    return await ResearchAgent().run({**BASE, **overrides})


class TestOutputContract:
    async def test_output_validates_against_the_schema(self):
        report = await run(industry="Healthcare", employees=1200)
        ResearchOutput.model_validate({k: v for k, v in report.items() if k in ResearchOutput.model_fields})

    async def test_carries_model_identity(self):
        report = await run()
        assert report["model_name"] == "research"
        assert report["model_version"] == MODEL_VERSION

    async def test_works_with_only_a_company_name(self):
        """Most fields on a fresh lead are empty; the agent must still produce
        a valid report rather than raising."""

        report = await run()
        assert report["company_summary"].startswith("MedCare Hospital")
        assert report["recent_news"] == []


class TestEvidenceVersusInference:
    """The core design rule: a fact and a guess have different shapes, so
    downstream code cannot render one as the other."""

    async def test_evidence_always_carries_a_source(self):
        report = await run(source="linkedin", crm_notes=["Budget approval expected in Q3"])
        assert report["recent_news"]
        for item in report["recent_news"]:
            assert item["claim"] and item["source"], item

    async def test_hypotheses_always_carry_a_basis(self):
        report = await run(industry="Healthcare", employees=1200)
        assert report["pain_points"]
        for item in report["pain_points"]:
            assert item["statement"] and item["basis"], item

    async def test_the_two_shapes_are_distinguishable(self):
        report = await run(industry="Healthcare", source="webform")
        assert set(report["recent_news"][0]) == {"claim", "source"}
        assert set(report["pain_points"][0]) == {"statement", "basis"}

    async def test_no_invented_news(self):
        """With nothing to cite, the honest answer is an empty list — not a
        plausible-sounding filler item."""

        report = await run(industry="Healthcare", employees=1200)
        assert report["recent_news"] == []

    async def test_crm_notes_become_attributed_evidence(self):
        note = "They mentioned budget approval in Q3"
        report = await run(crm_notes=[note])
        assert any(e["claim"] == note and e["source"] == "crm_notes" for e in report["recent_news"])

    async def test_unknown_industry_yields_no_invented_opportunity(self):
        """A generic 'AI automation opportunity' on every lead is noise reps
        learn to ignore, which devalues the real ones."""

        report = await run(industry="Underwater Basket Weaving")
        assert report["sales_opportunities"] == []


class TestIndustryPlaybook:
    async def test_healthcare_lead_gets_sector_hypotheses(self):
        report = await run(industry="Healthcare")
        statements = [p["statement"] for p in report["pain_points"]]
        assert any("patient" in s.lower() for s in statements), statements

    async def test_industry_match_is_case_insensitive(self):
        """The playbook lookup ignores case. `basis` still echoes the lead's
        own spelling, since it quotes the actual field value back."""

        lower = await run(industry="healthcare")
        upper = await run(industry="HEALTHCARE")
        assert [p["statement"] for p in lower["pain_points"]] == [
            p["statement"] for p in upper["pain_points"]
        ]

    @pytest.mark.parametrize(
        "employees,expected",
        [(10, "Small"), (200, "Mid-market"), (5000, "Enterprise")],
    )
    async def test_size_banding(self, employees, expected):
        report = await run(employees=employees)
        assert report["company_size_estimate"].startswith(expected)

    async def test_large_headcount_adds_a_scale_hypothesis(self):
        report = await run(employees=5000)
        assert any("Large-scale" in p["statement"] for p in report["pain_points"])


class TestConfidence:
    """Confidence is evidence *coverage*, computed from observable signals —
    never a number the model reports about itself."""

    async def test_more_data_scores_higher(self):
        thin = await run()
        rich = await run(
            industry="Healthcare",
            website="https://medcare.example.com",
            employees=1200,
            crm_notes=["Spoke to the CTO"],
            source="linkedin",
        )
        assert rich["confidence"] > thin["confidence"]

    async def test_empty_lead_scores_zero(self):
        assert (await run())["confidence"] == 0.0

    async def test_confidence_is_bounded(self):
        report = await run(
            industry="Healthcare",
            website="https://x.example.com",
            employees=10,
            crm_notes=["a"],
            source="linkedin",
        )
        assert 0.0 <= report["confidence"] <= 1.0

    def test_weights_sum_to_one(self):
        assert sum(confidence.WEIGHTS.values()) == pytest.approx(1.0)

    def test_thin_reports_are_flagged_unactionable(self):
        assert not confidence.is_actionable(0.1)
        assert confidence.is_actionable(0.9)

    async def test_explanation_states_what_was_missing(self):
        """A bare number is uninterpretable; the rep needs to know the report
        is thin because there was no website, not because we doubt the data."""

        report = await run(industry="Healthcare")
        assert "missing" in report["explanation"]
        assert "Insufficient data" in report["explanation"]


class TestSSRFGuard:
    """`Lead.website` is user input, and a fetched page would be persisted and
    shown to a user — so a bad URL is an exfiltration channel, not just a
    blind request."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://127.0.0.1:6379/",  # our own Redis
            "http://localhost:8000/",
            "http://10.0.0.5/internal",
            "http://192.168.1.1/",
        ],
    )
    def test_internal_addresses_rejected(self, url):
        with pytest.raises(UnsafeURLError):
            validate_fetchable_url(url)

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x/", "ftp://x/"])
    def test_non_http_schemes_rejected(self, url):
        with pytest.raises(UnsafeURLError):
            validate_fetchable_url(url)

    def test_unresolvable_host_rejected(self):
        with pytest.raises(UnsafeURLError):
            validate_fetchable_url("http://this-host-does-not-exist.invalid/")

    def test_hostname_blocklisting_alone_would_be_insufficient(self):
        """A public-looking name can resolve to loopback, which is why the
        check runs against the resolved IP rather than the string."""

        with pytest.raises(UnsafeURLError):
            validate_fetchable_url("http://localhost.localdomain/")


class TestOrchestration:
    """End to end through the orchestrator, which owns persistence."""

    async def test_report_is_persisted_with_structured_fields(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        lead = await db.get(Lead, tenant.lead_id)
        lead.industry = "Healthcare"
        lead.employees = 1200
        job = Job(
            company_id=tenant.company_id,
            job_type="lead_intelligence",
            lead_id=lead.id,
            created_by_user_id=tenant.exec_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()

        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        row = (
            await db.execute(
                text(
                    "SELECT summary, pain_points, sales_opportunities, confidence, explanation "
                    "FROM ai_research_reports"
                )
            )
        ).one()
        summary, pain_points, opportunities, conf, explanation = row
        assert "MedCare" in summary or tenant_lead_name_in(summary)
        assert pain_points and opportunities, "healthcare lead should produce hypotheses"
        assert 0.0 <= conf <= 1.0
        assert explanation and explanation != summary, "explanation must be reasoning, not a copy"

    async def test_research_lands_on_the_lead_timeline(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        lead = await db.get(Lead, tenant.lead_id)
        job = Job(
            company_id=tenant.company_id,
            job_type="lead_intelligence",
            lead_id=lead.id,
            created_by_user_id=tenant.exec_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()

        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)

        kinds = (
            await db.execute(text("SELECT activity_type FROM crm_activities"))
        ).scalars().all()
        assert "ai_research_generated" in kinds

    async def test_crm_notes_reach_the_agent(self, db, tenant):
        """The orchestrator gathers notes because the agent never queries the
        database itself."""

        from app.models.crm import Note
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        db.add(
            Note(
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                author_id=tenant.exec_id,
                body="CTO confirmed budget for next quarter",
            )
        )
        await db.commit()

        lead = await db.get(Lead, tenant.lead_id)
        payload = await AIOrchestrator(db)._build_research_input(lead)
        assert payload["crm_notes"] == ["CTO confirmed budget for next quarter"]

        report = await ResearchAgent().run(payload)
        assert any(e["source"] == "crm_notes" for e in report["recent_news"])


def tenant_lead_name_in(summary: str) -> bool:
    return "Prospect" in summary


class TestInputContract:
    def test_rejects_a_payload_without_a_company_name(self):
        with pytest.raises(ValueError):
            ResearchInput.model_validate({"lead_id": "x"})

    def test_defaults_crm_notes_to_empty(self):
        payload = ResearchInput.model_validate({"lead_id": "x", "company_name": "Acme"})
        assert payload.crm_notes == []
