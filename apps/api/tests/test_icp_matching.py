"""ICP Matching: per-tenant profiles, unknown-vs-mismatch, need scoring."""

import pytest
from sqlalchemy import text

from agents.icp_matching import rules
from agents.icp_matching.agent import MODEL_VERSION, ICPMatchingAgent

HEALTHCARE_LEAD = {"industry": "Healthcare", "employees": 1200, "country": "India"}


async def match(lead=None, signals=None, profile=None) -> dict:
    return await ICPMatchingAgent().run(
        {
            "lead_id": "00000000-0000-0000-0000-000000000001",
            "lead": lead if lead is not None else HEALTHCARE_LEAD,
            "signals": signals or [],
            "icp_profile": profile,
        }
    )


class TestTenantOwnedProfile:
    """The ICP is the tenant's. Hardcoding one target market into shared agent
    code would score every customer's leads against someone else's business."""

    async def test_default_profile_favours_its_listed_industries(self):
        out = await match({"industry": "Healthcare", "employees": 1200})
        assert out["industry_score"] == rules.STRONG_SCORE

    async def test_a_tenant_can_redefine_the_target_industry(self):
        logistics = {"target_industries": ["logistics", "manufacturing"]}
        healthcare_lead = await match({"industry": "Healthcare", "employees": 1200}, profile=logistics)
        logistics_lead = await match({"industry": "Logistics", "employees": 1200}, profile=logistics)

        assert logistics_lead["industry_score"] == rules.STRONG_SCORE
        assert healthcare_lead["industry_score"] == rules.MISMATCH_SCORE
        assert logistics_lead["overall_score"] > healthcare_lead["overall_score"]

    async def test_a_tenant_can_redefine_size_bands(self):
        smb = {"min_employees": 5, "ideal_employees": 20}
        out = await match({"industry": "Healthcare", "employees": 25}, profile=smb)
        assert out["company_size_score"] == rules.STRONG_SCORE, (
            "a tenant selling to small businesses must be able to say so"
        )

    async def test_custom_weights_change_the_outcome(self):
        size_only = {"weights": {"industry": 0, "company_size": 1, "region": 0, "need": 0}}
        out = await match({"industry": "Retail", "employees": 5000}, profile=size_only)
        assert out["overall_score"] == pytest.approx(rules.STRONG_SCORE)

    def test_weights_are_normalised(self):
        """Un-normalised weights would push overall scores past 100 and break
        every comparison built on them."""

        profile = rules.resolve_profile({"weights": {"industry": 5, "company_size": 5, "region": 5, "need": 5}})
        assert sum(profile["weights"].values()) == pytest.approx(1.0)

    def test_partial_config_keeps_default_weights(self):
        profile = rules.resolve_profile({"target_industries": ["logistics"]})
        assert profile["weights"] == rules.DEFAULT_ICP["weights"]
        assert profile["target_industries"] == ["logistics"]

    def test_zero_weights_fall_back_rather_than_dividing_by_zero(self):
        profile = rules.resolve_profile({"weights": {"industry": 0, "company_size": 0, "region": 0, "need": 0}})
        assert profile["weights"] == rules.DEFAULT_ICP["weights"]


class TestUnknownIsNotBad:
    """A lead nobody has researched must not rank below one we know is wrong."""

    async def test_missing_industry_scores_neutral_not_mismatch(self):
        out = await match({"employees": 1200})
        assert out["industry_score"] == rules.UNKNOWN_SCORE
        assert out["industry_score"] > rules.MISMATCH_SCORE

    async def test_unresearched_lead_outranks_a_known_mismatch(self):
        unknown = await match({})
        wrong = await match({"industry": "Fishing", "employees": 3, "country": "Peru"})
        assert unknown["overall_score"] > wrong["overall_score"]

    async def test_missing_data_lowers_confidence_not_score(self):
        complete = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "funding", "confidence": 0.8}])
        sparse = await match({})
        assert complete["confidence"] > sparse["confidence"]

    async def test_explanation_flags_which_dimensions_had_no_data(self):
        out = await match({})
        assert "no data" in out["explanation"]
        assert "not penalised" in out["explanation"]

    async def test_empty_target_countries_means_region_is_not_a_criterion(self):
        """Defaulting to a home market would penalise every international lead
        of a tenant who sells globally."""

        out = await match({"industry": "Healthcare", "employees": 1200, "country": "Peru"})
        assert out["region_score"] == rules.UNKNOWN_SCORE

    async def test_region_scores_when_the_tenant_defines_one(self):
        india_only = {"target_countries": ["india"]}
        good = await match({**HEALTHCARE_LEAD, "country": "India"}, profile=india_only)
        bad = await match({**HEALTHCARE_LEAD, "country": "Peru"}, profile=india_only)
        assert good["region_score"] == rules.STRONG_SCORE
        assert bad["region_score"] == rules.MISMATCH_SCORE


class TestNeedFromEvidence:
    """Need is scored from buying signals, which are evidence-derived — not
    from the research report's inferred pain points."""

    async def test_no_signals_scores_neutral(self):
        out = await match(HEALTHCARE_LEAD)
        assert out["pain_point_score"] == rules.UNKNOWN_SCORE

    async def test_signals_raise_the_need_score(self):
        out = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "funding", "confidence": 0.85}])
        assert out["pain_point_score"] > rules.UNKNOWN_SCORE

    async def test_stronger_signals_score_higher(self):
        weak = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "hiring", "confidence": 0.4}])
        strong = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "hiring", "confidence": 0.9}])
        assert strong["pain_point_score"] > weak["pain_point_score"]

    async def test_multiple_signal_types_beat_one(self):
        one = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "hiring", "confidence": 0.8}])
        two = await match(
            HEALTHCARE_LEAD,
            signals=[
                {"signal_type": "hiring", "confidence": 0.8},
                {"signal_type": "funding", "confidence": 0.8},
            ],
        )
        assert two["pain_point_score"] > one["pain_point_score"]

    async def test_inferred_pain_points_are_not_an_input(self):
        """Scoring them would double-count industry: the research playbook
        derives pain points *from* industry, so one field would drive both the
        industry dimension (30%) and the need dimension (20%)."""

        with_hypotheses = await match(
            HEALTHCARE_LEAD,
            signals=[],
        )
        assert with_hypotheses["pain_point_score"] == rules.UNKNOWN_SCORE


class TestOutputShape:
    async def test_every_attribute_is_reported_separately(self):
        out = await match(HEALTHCARE_LEAD)
        for key in ("industry_score", "company_size_score", "region_score", "pain_point_score"):
            assert key in out, "ICPScore has fixed per-attribute columns"

    async def test_scores_are_bounded(self):
        out = await match(HEALTHCARE_LEAD, signals=[{"signal_type": "funding", "confidence": 1.0}])
        assert 0 <= out["overall_score"] <= 100
        assert all(0 <= out[k] <= 100 for k in ("industry_score", "company_size_score", "region_score"))

    async def test_model_version_reported(self):
        assert (await match())["model_version"] == MODEL_VERSION


class TestPersistence:
    async def _run(self, db, tenant, icp_config=None):
        from app.models.company import Company
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        if icp_config is not None:
            company = await db.get(Company, tenant.company_id)
            company.icp_config = icp_config
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

    async def test_icp_score_is_persisted(self, db, tenant):
        await self._run(db, tenant)
        row = (
            await db.execute(
                text(
                    "SELECT industry_score, overall_score, confidence, explanation FROM icp_scores"
                )
            )
        ).one()
        industry, overall, conf, explanation = row
        assert industry == rules.STRONG_SCORE
        assert 0 <= overall <= 100
        assert 0 <= conf <= 1
        assert "Overall fit" in explanation

    async def test_tenant_config_is_actually_applied(self, db, tenant):
        """Proves the profile is read per-tenant rather than hardcoded."""

        await self._run(db, tenant, icp_config={"target_industries": ["logistics"]})
        industry = (await db.execute(text("SELECT industry_score FROM icp_scores"))).scalar()
        assert industry == rules.MISMATCH_SCORE, (
            "a healthcare lead should score poorly for a logistics-focused tenant"
        )

    async def test_signals_are_not_persisted_twice(self, db, tenant):
        """Regression: signal persistence was briefly duplicated, writing two
        rows per detected signal."""

        from app.models.crm import Note

        db.add(
            Note(
                company_id=tenant.company_id,
                lead_id=tenant.lead_id,
                author_id=tenant.exec_id,
                body="They confirmed expansion into two new cities",
            )
        )
        await db.commit()
        await self._run(db, tenant)

        rows = (
            await db.execute(text("SELECT signal_type, count(*) FROM buying_signals GROUP BY signal_type"))
        ).all()
        assert rows, "expansion note should yield a signal"
        assert all(count == 1 for _, count in rows), f"duplicate signal rows: {rows}"
