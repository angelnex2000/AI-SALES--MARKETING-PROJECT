"""Explainability: attribution is measured, not asserted in parallel."""

import pytest

from agents.explainability import explainer
from agents.explainability.schemas import FactorSource
from agents.lead_scoring import model as scoring
from agents.lead_scoring.model import LeadScoringAgent

REFERRAL_LEAD = {
    "industry": "Healthcare",
    "employees": 1200,
    "annual_revenue": 5.0e8,
    "lead_source": "Customer Referral",
    "account_tier": "Mid-Market",
}
COLD_LEAD = {**REFERRAL_LEAD, "lead_source": "Cold Email"}


async def explain(lead=None, icp=None, signals=None):
    lead = lead if lead is not None else REFERRAL_LEAD
    score_output = await LeadScoringAgent().run(
        {"lead": lead, "icp": icp or {}, "signals": {"signals": signals or []}}
    )
    return explainer.explain(score_output=score_output, lead=lead), score_output


class TestExplanationsMatchThePrediction:
    """The failure this module exists to prevent: a page showing a low score
    above a glowing reason, because the reasons were computed by a second set
    of rules that never saw the model."""

    async def test_factors_are_attributed_to_the_model_or_a_score_component(self):
        result, _ = await explain(icp={"overall_score": 90}, signals=[{"confidence": 0.8}])
        for factor in result.positive_factors + result.negative_factors:
            assert factor.source in (FactorSource.MODEL, FactorSource.COMPONENT)

    async def test_no_factor_cites_a_feature_the_model_never_saw(self):
        """The course material's example negative factor, "No previous
        customer reply", is an engagement count deliberately excluded from the
        feature set — citing it would be a plain falsehood."""

        result, _ = await explain()
        text = " ".join(f.label.lower() for f in result.positive_factors + result.negative_factors)
        for forbidden in ("reply", "replies", "email opened", "meeting"):
            assert forbidden not in text

    async def test_positive_factors_have_positive_impact(self):
        result, _ = await explain(icp={"overall_score": 95}, signals=[{"confidence": 0.9}])
        assert all(f.impact > 0 for f in result.positive_factors)
        assert all(f.impact < 0 for f in result.negative_factors)

    async def test_icp_direction_follows_the_component_not_a_rule(self):
        """A rule saying "icp >= 90 -> excellent" would fire regardless of what
        the composed score actually did."""

        strong, _ = await explain(icp={"overall_score": 95})
        weak, _ = await explain(icp={"overall_score": 10})
        strong_labels = " ".join(f.label for f in strong.positive_factors)
        weak_labels = " ".join(f.label for f in weak.negative_factors)
        assert "Strong match" in strong_labels
        assert "Weak match" in weak_labels

    async def test_factors_are_ordered_by_impact(self):
        result, _ = await explain(icp={"overall_score": 95}, signals=[{"confidence": 0.9}])
        impacts = [f.impact for f in result.positive_factors]
        assert impacts == sorted(impacts, reverse=True)


class TestMeasuredAttribution:
    """Ablation: re-score with a feature group removed; the difference is that
    group's real contribution to this prediction."""

    async def test_lead_source_is_attributed_when_it_matters(self):
        """Customer referrals convert at 43% against cold email's 17%, so
        source should register as a real contributor."""

        referral, _ = await explain(REFERRAL_LEAD)
        labels = " ".join(
            f.label.lower() for f in referral.positive_factors + referral.negative_factors
        )
        assert "referral" in labels or "source" in labels

    async def test_a_weak_source_shows_as_a_negative_factor(self):
        cold, _ = await explain(COLD_LEAD)
        assert cold.negative_factors, "cold email should pull the score down"

    async def test_baseline_gives_the_factors_a_reference_point(self):
        """"+8 for industry" is meaningless without knowing what a featureless
        lead scores."""

        result, _ = await explain()
        assert 0 <= result.baseline_score <= 100

    async def test_negligible_factors_are_dropped(self):
        result, _ = await explain()
        assert all(
            abs(f.impact) >= explainer.MIN_IMPACT
            for f in result.positive_factors + result.negative_factors
        )

    async def test_a_featureless_lead_says_so_rather_than_inventing_reasons(self):
        result, _ = await explain({})
        assert result.positive_factors == [] or all(
            f.source == FactorSource.COMPONENT for f in result.positive_factors
        )
        assert "average" in result.summary.lower() or result.negative_factors or result.positive_factors


class TestRecommendation:
    """Advice is conditioned on confidence as well as score — acting on a
    barely-discriminating model teaches a team to distrust the product."""

    async def test_low_confidence_advises_manual_review(self, monkeypatch):
        monkeypatch.setattr(scoring, "_model_cache", {"loaded": (None, {})})
        result, output = await explain()
        assert output["confidence"] < 0.2
        assert "manual" in result.recommendation.lower()

    def test_confident_high_score_with_signals_says_contact_now(self):
        rec = explainer.recommend(
            {"score": 85, "confidence": 0.6, "components": {"signal_adjustment": 10}}
        )
        assert "now" in rec.lower()

    def test_confident_high_score_without_signals_is_less_urgent(self):
        rec = explainer.recommend({"score": 85, "confidence": 0.6, "components": {}})
        assert "now" not in rec.lower()

    def test_low_score_suggests_nurture_not_outreach(self):
        rec = explainer.recommend({"score": 15, "confidence": 0.6, "components": {}})
        assert "nurture" in rec.lower()


class TestUntrainedModel:
    async def test_explanation_still_produced_without_an_artifact(self, monkeypatch):
        monkeypatch.setattr(scoring, "_model_cache", {"loaded": (None, {})})
        result, _ = await explain()
        assert result.recommendation
        assert result.summary

    async def test_no_model_attribution_is_claimed_without_a_model(self, monkeypatch):
        """Ablation needs a model; without one there is nothing to measure and
        inventing factors would be fabrication."""

        monkeypatch.setattr(scoring, "_model_cache", {"loaded": (None, {})})
        result, _ = await explain()
        assert all(
            f.source == FactorSource.COMPONENT
            for f in result.positive_factors + result.negative_factors
        )


class TestEndpoint:
    async def _score_lead(self, db, tenant):
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

    async def test_returns_stored_factors(self, client, db, tenant):
        await self._score_lead(db, tenant)
        r = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/score-explanation",
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert 0 <= data["lead_score"] <= 100
        assert data["recommendation"]
        assert data["model_version"]

    async def test_404_before_any_score_exists(self, client, tenant):
        r = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/score-explanation",
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "NO_LEAD_SCORE"

    async def test_other_tenant_cannot_read_it(self, client, db, tenant, other_tenant):
        await self._score_lead(db, tenant)
        r = client.get(
            f"/api/v1/ai/leads/{tenant.lead_id}/score-explanation",
            headers=other_tenant.headers("sales_manager"),
        )
        assert r.status_code == 404

    async def test_factors_persist_alongside_the_score(self, db, tenant):
        """Stored with the prediction, not in a separate table that could
        drift out of sync with the number it explains."""

        from sqlalchemy import text

        await self._score_lead(db, tenant)
        row = (
            await db.execute(
                text("SELECT score, positive_factors, recommendation, baseline_score FROM lead_scores")
            )
        ).one()
        assert row[2], "recommendation stored"
        assert row[3] is not None, "baseline stored"


@pytest.mark.parametrize("score,confidence", [(95, 0.9), (50, 0.5), (5, 0.9)])
def test_recommendation_is_always_actionable(score, confidence):
    rec = explainer.recommend({"score": score, "confidence": confidence, "components": {}})
    assert rec and rec[0].isupper() and rec.endswith(".")
