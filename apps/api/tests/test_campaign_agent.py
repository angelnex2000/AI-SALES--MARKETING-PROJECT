"""Campaign Agent: audience selection, grounded strategy, empty-audience UX."""

from datetime import UTC, datetime

import pytest

from agents.campaign import rules
from agents.campaign.agent import MODEL_VERSION, CampaignAgent
from app.services import campaign_service


async def plan(*, goal=None, industry=None, audience=None, proof=None) -> dict:
    return await CampaignAgent().run(
        {
            "campaign_goal": goal,
            "industry": industry,
            "audience": audience or {"selected": 20, "considered": 100},
            "proof": proof or {},
        }
    )


class TestStrategy:
    async def test_goal_drives_the_cta_and_cadence(self):
        demos = await plan(goal="book_demos")
        signups = await plan(goal="drive_signups")
        assert "demo" in demos["cta"].lower()
        assert demos["sequence_length"] != signups["sequence_length"]

    async def test_regulated_industries_get_a_consultative_tone(self):
        """A high-energy growth pitch reads as unserious to a hospital
        procurement lead."""

        assert (await plan(industry="Healthcare"))["email_style"] == "Consultative"
        assert (await plan(industry="Software & SaaS"))["email_style"] == "Direct"

    async def test_unknown_goal_and_industry_still_produce_a_usable_plan(self):
        result = await plan(goal="something_new", industry="Underwater Basketry")
        assert result["cta"]
        assert result["sequence_length"] >= 1
        assert result["email_style"] == rules.DEFAULT_TONE

    async def test_model_version_reported(self):
        assert (await plan())["model_version"] == MODEL_VERSION


class TestGroundedProof:
    """The agent must never name a case study from its own knowledge — a
    tenant who never uploaded one would be shown an invented customer."""

    async def test_no_case_study_recommended_without_retrieval(self):
        result = await plan(industry="Healthcare")
        assert result["recommended_case_study"] is None
        assert result["grounded"] is False

    async def test_emits_a_query_for_rag_rather_than_an_answer(self):
        result = await plan(industry="Healthcare")
        assert "healthcare" in result["case_study_query"].lower()

    async def test_retrieved_case_study_is_used(self):
        result = await plan(
            industry="Healthcare",
            proof={"grounded": True, "title": "CityCare Hospital Case Study"},
        )
        assert result["recommended_case_study"] == "CityCare Hospital Case Study"
        assert result["grounded"] is True

    async def test_ungrounded_plan_warns_emails_must_avoid_claims(self):
        result = await plan(industry="Healthcare", proof={"fallback_note": "No verified proof."})
        assert "avoid specific claims" in result["explanation"]
        assert result["proof_note"] == "No verified proof."

    async def test_grounding_raises_confidence(self):
        bare = await plan(audience={"selected": 20, "considered": 100})
        grounded = await plan(
            audience={"selected": 20, "considered": 100},
            proof={"grounded": True, "title": "X"},
        )
        assert grounded["confidence"] > bare["confidence"]


class TestEmptyAudience:
    """The most common real outcome. A bare "0 leads" is unactionable."""

    async def test_zero_audience_floors_confidence(self):
        result = await plan(audience={"selected": 0, "considered": 250})
        assert result["confidence"] == 0.0

    async def test_explanation_names_the_limiting_filter(self):
        result = await plan(
            audience={"selected": 0, "considered": 250, "limiting_criterion": "lead_score"}
        )
        assert "lead_score" in result["explanation"]
        assert "Relax" in result["explanation"]

    async def test_explanation_suggests_running_intelligence_first(self):
        result = await plan(audience={"selected": 0, "considered": 250})
        assert "lead intelligence" in result["explanation"]


class TestAudienceSelection:
    async def _leads(self, db, tenant, specs):
        """specs: list of (industry, employees, country)."""

        from app.models.lead import Lead

        created = []
        for industry, employees, country in specs:
            lead = Lead(
                company_id=tenant.company_id,
                name=f"{industry}-{employees}",
                industry=industry,
                employees=employees,
                country=country,
                owner_id=tenant.exec_id,
            )
            db.add(lead)
            await db.flush()
            created.append(lead)
        await db.commit()
        return created

    async def _score(self, db, tenant, lead, *, score=None, icp=None, signal_types=()):
        from app.models.lead import BuyingSignal, ICPScore, LeadScore

        if score is not None:
            db.add(
                LeadScore(
                    company_id=tenant.company_id, lead_id=lead.id, score=score,
                    model_name="t", model_version="t", confidence=0.5, explanation="",
                )
            )
        if icp is not None:
            db.add(
                ICPScore(
                    company_id=tenant.company_id, lead_id=lead.id, industry_score=icp,
                    company_size_score=icp, region_score=icp, pain_point_score=icp,
                    overall_score=icp, model_name="t", model_version="t",
                    confidence=0.5, explanation="",
                )
            )
        for kind in signal_types:
            db.add(
                BuyingSignal(
                    company_id=tenant.company_id, lead_id=lead.id, signal_type=kind,
                    description="d", detected_at=datetime.now(UTC),
                    model_name="t", model_version="t", confidence=0.8, explanation="",
                )
            )
        await db.commit()

    async def test_filters_by_industry(self, db, tenant):
        await self._leads(db, tenant, [("Healthcare", 900, "India"), ("Retail", 900, "India")])
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, industry="Healthcare"
        )
        assert result["selected"] == 1

    async def test_unscored_leads_are_included_by_default(self, db, tenant):
        """A new workspace has no scores at all; excluding unscored leads
        would make every first campaign empty with no explanation."""

        await self._leads(db, tenant, [("Healthcare", 900, "India")])
        result = await campaign_service.select_audience(db, company_id=tenant.company_id)
        assert result["selected"] >= 1

    async def test_unscored_can_be_excluded_explicitly(self, db, tenant):
        await self._leads(db, tenant, [("Healthcare", 900, "India")])
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, criteria={"include_unscored": False}
        )
        assert result["selected"] == 0
        assert result["eliminated"]["unscored"] >= 1

    async def test_low_scoring_leads_are_filtered_out(self, db, tenant):
        leads = await self._leads(db, tenant, [("Healthcare", 900, "India")])
        await self._score(db, tenant, leads[0], score=20)
        result = await campaign_service.select_audience(
            db,
            company_id=tenant.company_id,
            industry="Healthcare",  # isolates from the fixture's industry-less lead
            criteria={"min_lead_score": 60},
        )
        assert result["selected"] == 0
        assert result["limiting_criterion"] == "lead_score"

    async def test_only_the_latest_score_counts(self, db, tenant):
        """lead_scores is append-only; an old low score must not veto a lead
        that has since been rescored."""

        leads = await self._leads(db, tenant, [("Healthcare", 900, "India")])
        await self._score(db, tenant, leads[0], score=10)
        await self._score(db, tenant, leads[0], score=95)
        result = await campaign_service.select_audience(
            db,
            company_id=tenant.company_id,
            industry="Healthcare",
            criteria={"min_lead_score": 60},
        )
        assert result["selected"] == 1

    async def test_signal_requirement_counts_distinct_types(self, db, tenant):
        """buying_signals is append-only, so counting rows would reward
        re-running the pipeline rather than measuring real breadth."""

        leads = await self._leads(db, tenant, [("Healthcare", 900, "India")])
        await self._score(db, tenant, leads[0], score=90, signal_types=("expansion", "expansion"))
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, criteria={"min_buying_signals": 2}
        )
        assert result["selected"] == 0, "two rows of one signal type is one signal"

        await self._score(db, tenant, leads[0], signal_types=("hiring",))
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, criteria={"min_buying_signals": 2}
        )
        assert result["selected"] == 1

    async def test_archived_leads_are_excluded(self, db, tenant):
        leads = await self._leads(db, tenant, [("Healthcare", 900, "India")])
        leads[0].archived_at = datetime.now(UTC)
        await db.commit()
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, industry="Healthcare"
        )
        assert result["selected"] == 0

    async def test_other_tenants_leads_are_never_selected(self, db, tenant, other_tenant):
        await self._leads(db, tenant, [("Healthcare", 900, "India")])
        result = await campaign_service.select_audience(
            db, company_id=other_tenant.company_id, industry="Healthcare"
        )
        assert result["selected"] == 0

    async def test_reports_which_criterion_eliminated_the_most(self, db, tenant):
        leads = await self._leads(
            db, tenant, [("Healthcare", 900, "India"), ("Healthcare", 900, "India")]
        )
        for lead in leads:
            await self._score(db, tenant, lead, score=10, icp=95)
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, criteria={"min_lead_score": 80}
        )
        assert result["limiting_criterion"] == "lead_score"
        assert result["eliminated"]["lead_score"] == 2

    async def test_audience_is_capped_and_reports_truncation(self, db, tenant):
        await self._leads(db, tenant, [("Healthcare", 900, "India")] * 5)
        result = await campaign_service.select_audience(
            db, company_id=tenant.company_id, criteria={"max_audience": 2}
        )
        assert result["selected"] == 2
        assert result["truncated"] is True

    async def test_returns_lead_ids_as_a_snapshot(self, db, tenant):
        """Stored ids, not a saved query — re-running at send time would
        change the audience between approval and delivery."""

        await self._leads(db, tenant, [("Healthcare", 900, "India")])
        result = await campaign_service.select_audience(db, company_id=tenant.company_id)
        assert len(result["lead_ids"]) == result["selected"]


@pytest.mark.parametrize("value,expected", [(0, 1), (99999, 5000)])
def test_max_audience_is_clamped(value, expected):
    assert rules.resolve_criteria({"max_audience": value})["max_audience"] == expected
