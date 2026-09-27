"""Lead scoring: feature contract, leakage guards, ranking behaviour."""

import pytest
from sqlalchemy import text

from agents.lead_scoring import model as scoring_model
from agents.lead_scoring.features import (
    FEATURE_COUNT,
    FEATURE_NAMES,
    INDUSTRIES,
    LEAD_SOURCES,
    LEAKING_FIELDS,
    build_features,
    describe_features,
)
from agents.lead_scoring.model import LeadScoringAgent

REFERRAL_LEAD = {
    "industry": "Healthcare",
    "employees": 1200,
    "annual_revenue": 5.0e8,
    "lead_source": "Customer Referral",
    "account_tier": "Mid-Market",
}
COLD_LEAD = {**REFERRAL_LEAD, "lead_source": "Cold Email"}


async def score(lead=None, icp=None, signals=None) -> dict:
    return await LeadScoringAgent().run(
        {
            "lead": lead if lead is not None else REFERRAL_LEAD,
            "icp": icp or {},
            "signals": {"signals": signals or []},
        }
    )


class TestFeatureContract:
    """One transformation shared by training and inference — train/serve skew
    produces a model that scores well offline and badly in production."""

    def test_vector_width_is_fixed(self):
        assert len(build_features(REFERRAL_LEAD)) == FEATURE_COUNT == len(FEATURE_NAMES)

    def test_empty_lead_still_produces_a_full_vector(self):
        assert len(build_features({})) == FEATURE_COUNT

    def test_unknown_category_lands_in_the_other_bucket(self):
        """An all-zero block would be a state the model never saw in training."""

        active = describe_features(build_features({"industry": "Underwater Basket Weaving"}))
        assert active.get("industry=other") == 1.0

    def test_known_category_does_not_hit_other(self):
        active = describe_features(build_features({"industry": "Healthcare"}))
        assert active.get("industry=healthcare") == 1.0
        assert "industry=other" not in active

    def test_category_matching_is_case_insensitive(self):
        assert build_features({"industry": "HEALTHCARE"}) == build_features({"industry": "healthcare"})

    def test_missing_numeric_is_distinguishable_from_zero(self):
        """A lead with no headcount recorded is not a company with no staff;
        collapsing the two teaches the model that missing means tiny."""

        missing = describe_features(build_features({}))
        present = describe_features(build_features({"employees": 500}))
        assert "has_employees" not in missing
        assert present["has_employees"] == 1.0

    def test_large_values_are_compressed(self):
        """Log scaling stops one 500,000-employee company dominating."""

        big = describe_features(build_features({"employees": 500_000}))
        small = describe_features(build_features({"employees": 50}))
        assert big["log_employees"] <= 1.0
        assert big["log_employees"] > small["log_employees"]

    def test_source_levels_match_the_training_data(self):
        """These were once written from memory and mismatched the real values,
        collapsing the strongest predictor into `other` and costing ~0.09 AUC."""

        assert "customer referral" in LEAD_SOURCES
        assert "cold email" in LEAD_SOURCES
        assert "outbound - sdr" in LEAD_SOURCES

    def test_industry_levels_cover_the_training_data(self):
        for expected in ("healthcare", "software & saas", "non-profit", "automotive"):
            assert expected in INDUSTRIES


class TestLeakageGuards:
    """Post-outcome fields must never become features."""

    @pytest.mark.parametrize(
        "field", ["stage", "probability", "forecast_category", "sales_cycle_days"]
    )
    def test_post_outcome_crm_fields_are_listed_as_leaking(self, field):
        assert field in LEAKING_FIELDS

    @pytest.mark.parametrize(
        "field", ["meetings_completed", "emails_opened", "replies_received", "activity_count"]
    )
    def test_engagement_fields_are_listed_as_leaking(self, field):
        """These are consequences of working a lead, and are zero for every
        lead a rep is deciding whether to call — so a model trained on them
        has never seen the distribution it must predict on."""

        assert field in LEAKING_FIELDS

    def test_no_leaking_field_is_a_feature(self):
        for name in FEATURE_NAMES:
            assert name not in LEAKING_FIELDS


class TestScoring:
    async def test_score_is_bounded(self):
        out = await score(icp={"overall_score": 100}, signals=[{"confidence": 1.0}])
        assert 0 <= out["score"] <= 100

    async def test_referral_outranks_cold_email(self):
        """The strongest real signal in the historical data: customer
        referrals convert at 43%, cold email at 17%."""

        referral = await score(REFERRAL_LEAD)
        cold = await score(COLD_LEAD)
        assert referral["score"] > cold["score"]

    async def test_components_are_reported_separately(self):
        """A rep who disagrees with a score must be able to see which of the
        three inputs drove it."""

        out = await score(icp={"overall_score": 90}, signals=[{"confidence": 0.8}])
        assert set(out["components"]) == {
            "historical_fit",
            "icp_adjustment",
            "signal_adjustment",
        }

    async def test_good_icp_raises_and_poor_icp_lowers(self):
        high = await score(icp={"overall_score": 95})
        low = await score(icp={"overall_score": 20})
        assert high["score"] > low["score"]
        assert high["components"]["icp_adjustment"] > 0 > low["components"]["icp_adjustment"]

    async def test_signals_can_only_help_within_a_bound(self):
        """Uncapped, a lead with signals would saturate at 100 regardless of
        whether the company resembles anyone we have sold to."""

        none = await score(signals=[])
        many = await score(signals=[{"confidence": 1.0}, {"confidence": 0.9}])
        assert many["score"] > none["score"]
        assert many["components"]["signal_adjustment"] <= scoring_model.SIGNAL_WEIGHT * 100 + 0.01

    async def test_explanation_states_how_the_score_was_built(self):
        out = await score(icp={"overall_score": 90}, signals=[{"confidence": 0.8}])
        assert "Historical fit" in out["explanation"]
        assert "ICP fit" in out["explanation"]

    async def test_active_features_are_named_for_explainability(self):
        out = await score(REFERRAL_LEAD)
        assert "industry=healthcare" in out["active_features"]
        assert "source=customer referral" in out["active_features"]


class TestConfidenceIsMeasuredNotInvented:
    async def test_confidence_reflects_model_discrimination(self, monkeypatch):
        """AUC 0.5 is random. Confidence must fall out of the holdout metric,
        not be asserted per prediction — otherwise a weak model presents as a
        certain one."""

        monkeypatch.setattr(scoring_model, "_model_cache", {"loaded": (None, {})})
        untrained = await score()
        assert untrained["confidence"] <= 0.2, "an untrained fallback must not look confident"

    async def test_untrained_fallback_still_ranks(self, monkeypatch):
        """A constant score makes the Leads list unsortable and reads as a
        broken feature."""

        monkeypatch.setattr(scoring_model, "_model_cache", {"loaded": (None, {})})
        referral = await score(REFERRAL_LEAD)
        cold = await score(COLD_LEAD)
        assert referral["score"] > cold["score"]
        assert referral["model_version"] == scoring_model.HEURISTIC_VERSION

    async def test_corrupt_artifact_falls_back_rather_than_crashing(self, monkeypatch, tmp_path):
        bad = tmp_path / "lead_scoring.joblib"
        bad.write_text("not a joblib file", encoding="utf-8")
        monkeypatch.setattr(scoring_model, "MODEL_PATH", bad)
        scoring_model.reset_cache()
        try:
            out = await score()
            assert out["model_version"] == scoring_model.HEURISTIC_VERSION
        finally:
            scoring_model.reset_cache()


class TestPersistence:
    async def test_score_is_stored_with_its_model_version(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.models.lead import Lead
        from app.services.ai_orchestrator import AIOrchestrator

        lead = await db.get(Lead, tenant.lead_id)
        lead.industry = "Healthcare"
        lead.employees = 1200
        lead.source = "Customer Referral"
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
                text("SELECT score, model_version, confidence, explanation FROM lead_scores")
            )
        ).one()
        score_value, version, confidence, explanation = row
        assert 0 <= score_value <= 100
        assert version, "model_version must record which model produced this prediction"
        assert 0 <= confidence <= 1
        assert "Score" in explanation
