"""Feedback Learning — edit distance, preserved AI text, and a quality report
that refuses to invent metrics.

The rule under test throughout: this is the panel an Admin uses to decide
whether the AI is getting better, and the numbers on it will be quoted. A
figure with no evidence behind it is worse than a blank.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import text

from agents.feedback_learning import edit_distance
from agents.feedback_learning.agent import (
    MIN_SAMPLE_FOR_DISPLAY,
    RETRAIN_THRESHOLDS,
    FeedbackLearningAgent,
)
from app.models.feedback import FeedbackTarget, FeedbackVerdict
from app.services import feedback_service

V1 = "/api/v1"

AI_DRAFT = (
    "Hi Rahul, I noticed MedCare Hospital expanded telemedicine services last quarter. "
    "Would you be open to a demo?"
)
LIGHT_POLISH = (
    "Hi Rahul, I noticed MedCare Hospital expanded telemedicine services last quarter. "
    "Would you be open to a short demo?"
)
FULL_REWRITE = (
    "Rahul, congratulations on the recent expansion. Are you free for twenty minutes on "
    "Tuesday to talk about reducing your patient inquiry backlog?"
)


def measure(original, final, *, subject_a="Quick question", subject_b="Quick question"):
    return edit_distance.measure(
        original_subject=subject_a,
        original_body=original,
        final_subject=subject_b,
        final_body=final,
    )


class TestEditDistance:
    def test_an_unedited_draft_is_zero(self):
        out = measure(AI_DRAFT, AI_DRAFT)
        assert out["edit_distance"] == 0.0
        assert out["verdict"] == edit_distance.VERDICT_ACCEPTED

    def test_a_small_polish_reads_as_a_good_draft(self):
        """The brief's point: a rep tweaking a word or two means the draft was
        useful, not that the AI failed."""

        out = measure(AI_DRAFT, LIGHT_POLISH)
        assert out["verdict"] == edit_distance.VERDICT_LIGHT
        assert out["edit_distance"] <= edit_distance.LIGHT_EDIT_MAX

    def test_a_rewrite_is_distinguishable_from_a_polish(self):
        polish = measure(AI_DRAFT, LIGHT_POLISH)
        rewrite = measure(AI_DRAFT, FULL_REWRITE)
        assert rewrite["edit_distance"] > polish["edit_distance"]
        assert rewrite["verdict"] in (
            edit_distance.VERDICT_HEAVY,
            edit_distance.VERDICT_REWRITTEN,
            edit_distance.VERDICT_MODERATE,
        )

    def test_casing_and_punctuation_are_not_disagreement(self):
        """"Hi Rahul," to "Hi Rahul" is not a human disagreeing with the AI,
        and counting it would put noise into a metric that decides whether a
        prompt is working."""

        assert measure("Hi Rahul, would you be open?", "hi rahul would you be open")[
            "edit_distance"
        ] == 0.0

    def test_subject_is_measured_separately(self):
        """A subject rewritten every time is a subject-prompt problem, and
        averaging it into a 400-word body hides it completely."""

        out = measure(AI_DRAFT, AI_DRAFT, subject_a="Quick question", subject_b="Telemedicine ROI")
        assert out["subject_changed"] is True
        assert out["subject_distance"] > 0.9
        assert out["body_distance"] == 0.0
        # A three-word subject must not dominate a 20-word body.
        assert out["edit_distance"] < out["subject_distance"]

    def test_word_counts_are_reported(self):
        out = measure("one two three", "one two three four five")
        assert out["words_added"] == 2
        assert out["words_removed"] == 0

    @pytest.mark.parametrize(
        "original,final,expected",
        [("", "", 0.0), ("something", "", 1.0), ("", "something", 1.0)],
    )
    def test_empty_text_edges(self, original, final, expected):
        assert edit_distance._distance(
            edit_distance.tokenize(original), edit_distance.tokenize(final)
        ) == expected

    def test_verdict_bands_are_ordered(self):
        distances = [0.0, 0.1, 0.3, 0.6, 0.9]
        verdicts = [edit_distance.verdict_for(d) for d in distances]
        assert verdicts == [
            edit_distance.VERDICT_ACCEPTED,
            edit_distance.VERDICT_LIGHT,
            edit_distance.VERDICT_MODERATE,
            edit_distance.VERDICT_HEAVY,
            edit_distance.VERDICT_REWRITTEN,
        ]


# ------------------------------------------------------- preserving AI text


async def seed_draft(db, tenant, *, ai_generated=True, subject="Quick question", body=AI_DRAFT):
    from app.models.outreach import EmailDraft

    draft = EmailDraft(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        subject=subject,
        body=body,
        explanation="seed",
        ai_generated=ai_generated,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


class TestPreservingTheAIOriginal:
    """Without this, the platform's best feedback signal does not exist:
    editing overwrites body in place, so the AI's words were destroyed by the
    first keystroke and every edit distance would have been a flattering 0.0.
    """

    async def test_first_edit_snapshots_what_the_ai_wrote(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        client.put(
            f"{V1}/outreach/drafts/{draft.id}",
            json={"body": FULL_REWRITE},
            headers=tenant.headers("sales_executive"),
        )
        await db.refresh(draft)
        assert draft.ai_original_body == AI_DRAFT
        assert draft.body == FULL_REWRITE

    async def test_a_second_edit_keeps_the_original_original(self, client, db, tenant):
        """The metric wanted is total human divergence from the AI, not the
        size of the latest keystroke — otherwise a draft rewritten in three
        passes reads as three small tweaks."""

        draft = await seed_draft(db, tenant)
        headers = tenant.headers("sales_executive")
        client.put(f"{V1}/outreach/drafts/{draft.id}", json={"body": LIGHT_POLISH}, headers=headers)
        client.put(f"{V1}/outreach/drafts/{draft.id}", json={"body": FULL_REWRITE}, headers=headers)
        await db.refresh(draft)
        assert draft.ai_original_body == AI_DRAFT

    async def test_a_human_authored_draft_is_not_snapshotted(self, client, db, tenant):
        """There is no AI original to preserve, and recording one would put a
        human's own first attempt into the AI's quality metrics."""

        draft = await seed_draft(db, tenant, ai_generated=False)
        client.put(
            f"{V1}/outreach/drafts/{draft.id}",
            json={"body": FULL_REWRITE},
            headers=tenant.headers("sales_executive"),
        )
        await db.refresh(draft)
        assert draft.ai_original_body is None

    async def test_an_unedited_draft_has_no_original_and_that_is_the_signal(self, db, tenant):
        """Null means nobody edited it — the strongest positive signal there
        is, not missing data."""

        draft = await seed_draft(db, tenant)
        assert draft.ai_original_body is None


# -------------------------------------------------------------------- agent


async def report(**payload):
    return await FeedbackLearningAgent().run(payload)


class TestMetricHonesty:
    async def test_no_research_accuracy_metric_is_invented(self):
        """The brief's dashboard shows "Research Accuracy 92%". Nothing here
        can compute that — there is no ground truth for whether a report was
        correct, only for whether a human liked it."""

        out = await report()
        assert "research_accuracy" not in out["metrics"]
        assert out["metrics"]["research_satisfaction"]["unit"] == "mean_rating_1_5"

    async def test_an_unmeasurable_metric_says_why(self):
        out = await report()
        for name, value in out["metrics"].items():
            assert value["available"] is False, name
            assert value["unavailable_reason"], name
            assert value["value"] is None, name

    async def test_a_tiny_sample_is_not_reported_as_a_rate(self):
        """100% acceptance across two drafts is not 100% acceptance, and a
        dashboard showing it will be believed."""

        out = await report(drafts={"approved": 2, "rejected": 0})
        assert out["metrics"]["outreach_acceptance"]["available"] is False
        assert "at least" in out["metrics"]["outreach_acceptance"]["unavailable_reason"]

    async def test_a_real_sample_is_reported(self):
        out = await report(drafts={"approved": 18, "rejected": 2})
        acceptance = out["metrics"]["outreach_acceptance"]
        assert acceptance["available"] is True
        assert acceptance["value"] == 0.9
        assert acceptance["sample_size"] == 20

    async def test_pending_drafts_do_not_count_as_rejections(self):
        """Otherwise a busy week looks like a quality collapse."""

        decided = await report(drafts={"approved": 18, "rejected": 2})
        with_pending = await report(drafts={"approved": 18, "rejected": 2, "pending_approval": 40})
        assert decided["metrics"]["outreach_acceptance"] == with_pending["metrics"][
            "outreach_acceptance"
        ]

    async def test_every_metric_carries_its_sample_size(self):
        out = await report(drafts={"approved": 18, "rejected": 2})
        assert all("sample_size" in m for m in out["metrics"].values())

    async def test_explanation_names_what_is_missing(self):
        out = await report(drafts={"approved": 18, "rejected": 2})
        assert "Not yet measurable" in out["explanation"]


class TestDerivedMetrics:
    async def test_edit_rate_averages_stored_distances(self):
        edits = [{"edit_distance": 0.1, "verdict": "light_edit"} for _ in range(10)]
        out = await report(edits=edits)
        assert out["metrics"]["human_edit_rate"]["value"] == pytest.approx(0.1)

    async def test_no_edits_explains_that_distance_needs_an_original(self):
        out = await report()
        reason = out["metrics"]["human_edit_rate"]["unavailable_reason"]
        assert "AI original" in reason

    async def test_forecast_error_ignores_periods_still_running(self):
        """Scoring an open month reports a huge error simply because the month
        is not over."""

        errors = [
            {"absolute_percentage_error": 0.05, "period_closed": True},
            {"absolute_percentage_error": 0.04, "period_closed": True},
            {"absolute_percentage_error": 0.90, "period_closed": False},
            {"absolute_percentage_error": 0.03, "period_closed": True},
        ]
        out = await report(forecast_errors=errors)
        assert out["metrics"]["forecast_error"]["value"] == pytest.approx(0.04)
        assert out["metrics"]["forecast_error"]["sample_size"] == 3

    async def test_reply_intent_accuracy_declares_its_sampling_bias(self):
        """People correct errors far more readily than they confirm successes,
        so this is a lower bound, not accuracy."""

        out = await report(reply_intent={"reviewed": 20, "confirmed": 17})
        assert out["metrics"]["reply_intent_accuracy"]["value"] == 0.85
        assert any("lower bound" in note for note in out["observations"])

    async def test_unreviewed_classifications_are_not_counted_as_correct(self):
        out = await report(reply_intent={"reviewed": 0, "confirmed": 0})
        assert out["metrics"]["reply_intent_accuracy"]["available"] is False
        assert "no ground truth" in out["metrics"]["reply_intent_accuracy"]["unavailable_reason"]

    async def test_edit_breakdown_separates_polish_from_rewrites(self):
        """An average alone cannot tell "every draft needs a tidy" from "most
        are perfect and a third are binned"."""

        edits = [{"edit_distance": 0.05, "verdict": "light_edit", "subject_changed": False}] * 8 + [
            {"edit_distance": 0.9, "verdict": "rewritten", "subject_changed": True}
        ] * 4
        out = await report(edits=edits)
        assert out["edit_breakdown"]["by_verdict"] == {"light_edit": 8, "rewritten": 4}
        # Rounded to 4dp for display, so compare with matching tolerance.
        assert out["edit_breakdown"]["subject_change_rate"] == pytest.approx(4 / 12, abs=1e-4)


class TestObservationsAndRetraining:
    async def test_a_high_edit_rate_points_at_the_prompt(self):
        out = await report(edits=[{"edit_distance": 0.8, "verdict": "rewritten"}] * 12)
        assert any("prompt is the problem" in note for note in out["observations"])

    async def test_heavy_rejection_is_called_out(self):
        out = await report(drafts={"approved": 5, "rejected": 20})
        assert any("Gate 2 rejects" in note for note in out["observations"])

    async def test_readiness_never_says_retrain_now(self):
        """Feedback is a biased sample of a system humans already steer;
        retraining on it without a held-out evaluation teaches the model to
        agree with the reps and calls that an improvement."""

        out = await report(training_samples={k: v * 10 for k, v in RETRAIN_THRESHOLDS.items()})
        for row in out["retraining_readiness"]:
            assert row["ready_to_evaluate"] is True
            assert "evaluation" in row["next_step"]
            assert "retrain now" not in row["next_step"].lower()

    async def test_readiness_reports_the_shortfall(self):
        out = await report(training_samples={"outreach": 50})
        outreach = next(r for r in out["retraining_readiness"] if r["model"] == "outreach")
        assert outreach["ready_to_evaluate"] is False
        assert str(RETRAIN_THRESHOLDS["outreach"] - 50) in outreach["next_step"]

    async def test_all_models_are_listed(self):
        out = await report()
        assert {r["model"] for r in out["retraining_readiness"]} == set(RETRAIN_THRESHOLDS)


# ------------------------------------------------------------------ service


class TestRecordFeedback:
    async def test_feedback_is_stored_against_the_target(self, db, tenant):
        draft = await seed_draft(db, tenant)
        user = await _user(db, tenant.exec_id)
        record = await feedback_service.record_feedback(
            db,
            user=user,
            target_type=FeedbackTarget.EMAIL_DRAFT,
            target_id=draft.id,
            rating=5,
            verdict=FeedbackVerdict.HELPFUL,
        )
        assert record.rating == 5
        assert record.lead_id == tenant.lead_id
        assert record.author_id == tenant.exec_id

    async def test_rating_the_same_output_twice_updates_rather_than_stacks(self, db, tenant):
        """One enthusiastic user clicking five stars ten times would otherwise
        move an aggregate that feeds a retraining decision."""

        draft = await seed_draft(db, tenant)
        user = await _user(db, tenant.exec_id)
        for rating in (3, 5):
            await feedback_service.record_feedback(
                db,
                user=user,
                target_type=FeedbackTarget.EMAIL_DRAFT,
                target_id=draft.id,
                rating=rating,
            )
        rows = (await db.execute(text("SELECT rating FROM feedback_records"))).all()
        assert rows == [(5,)]

    async def test_a_different_person_gets_their_own_row(self, db, tenant):
        draft = await seed_draft(db, tenant)
        for user_id in (tenant.exec_id, tenant.manager_id):
            await feedback_service.record_feedback(
                db,
                user=await _user(db, user_id),
                target_type=FeedbackTarget.EMAIL_DRAFT,
                target_id=draft.id,
                rating=4,
            )
        count = (await db.execute(text("SELECT count(*) FROM feedback_records"))).scalar()
        assert count == 2

    async def test_empty_feedback_is_rejected(self, db, tenant):
        from app.core.exceptions import ValidationError

        draft = await seed_draft(db, tenant)
        with pytest.raises(ValidationError):
            await feedback_service.record_feedback(
                db,
                user=await _user(db, tenant.exec_id),
                target_type=FeedbackTarget.EMAIL_DRAFT,
                target_id=draft.id,
                comment="nice",
            )

    async def test_another_tenants_output_is_404(self, db, tenant, other_tenant):
        from app.core.exceptions import NotFoundError

        draft = await seed_draft(db, other_tenant)
        with pytest.raises(NotFoundError):
            await feedback_service.record_feedback(
                db,
                user=await _user(db, tenant.exec_id),
                target_type=FeedbackTarget.EMAIL_DRAFT,
                target_id=draft.id,
                rating=5,
            )

    async def test_an_unassigned_executive_cannot_rate_it(self, db, tenant):
        """Rating an output would otherwise confirm that it exists."""

        from app.core.exceptions import NotFoundError

        draft = await seed_draft(db, tenant)
        with pytest.raises(NotFoundError):
            await feedback_service.record_feedback(
                db,
                user=await _user(db, tenant.exec2_id),
                target_type=FeedbackTarget.EMAIL_DRAFT,
                target_id=draft.id,
                rating=5,
            )


async def _user(db, user_id):
    from app.models.user import User

    return await db.get(User, user_id)


class TestQualityReport:
    async def test_edits_feed_the_report(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        client.put(
            f"{V1}/outreach/drafts/{draft.id}",
            json={"body": FULL_REWRITE},
            headers=tenant.headers("sales_executive"),
        )
        out = await feedback_service.quality_report(db, company_id=tenant.company_id)
        assert out["edit_breakdown"]["sample_size"] == 1

    async def test_a_sent_draft_still_counts_as_accepted(self, db, tenant):
        """Counting only `approved` would make the acceptance rate fall every
        time somebody actually sends an email."""

        from app.models.outreach import DraftStatus

        draft = await seed_draft(db, tenant)
        draft.status = DraftStatus.SENT
        await db.commit()
        counts = await feedback_service._draft_counts(db, tenant.company_id)
        assert counts["approved"] == 1

    async def test_forecast_error_uses_actual_closed_revenue(self, db, tenant):
        """The one metric with real ground truth, and the reason forecasts are
        stored rather than recomputed."""

        from app.models.deal import Deal, DealStage
        from app.models.feedback import DealOutcome, Outcome
        from app.models.forecast import RevenueForecast

        deal = Deal(
            company_id=tenant.company_id,
            lead_id=tenant.lead_id,
            name="Won",
            stage=DealStage.CLOSED_WON,
            amount=Decimal("100000"),
            currency="INR",
        )
        db.add(deal)
        await db.flush()
        db.add(
            DealOutcome(
                company_id=tenant.company_id,
                deal_id=deal.id,
                lead_id=tenant.lead_id,
                outcome=Outcome.WON,
                closed_at=datetime(2026, 1, 15, tzinfo=UTC),
            )
        )
        db.add(
            RevenueForecast(
                company_id=tenant.company_id,
                forecast_period="2026-01",
                currency="INR",
                predicted_revenue=Decimal("80000"),
                committed_revenue=Decimal("0"),
                weighted_pipeline=Decimal("80000"),
                confidence=0.6,
                model_name="revenue_forecasting",
                model_version="v1",
                explanation="seed",
            )
        )
        await db.commit()

        errors = await feedback_service._forecast_errors(db, tenant.company_id)
        assert len(errors) == 1
        assert errors[0]["period_closed"] is True
        assert errors[0]["absolute_percentage_error"] == pytest.approx(0.2)

    async def test_another_tenants_feedback_is_not_counted(self, db, tenant, other_tenant):
        draft = await seed_draft(db, other_tenant)
        draft.ai_original_body = AI_DRAFT
        draft.body = FULL_REWRITE
        await db.commit()
        out = await feedback_service.quality_report(db, company_id=tenant.company_id)
        assert out["edit_breakdown"]["sample_size"] == 0


# ---------------------------------------------------------------------- API


class TestFeedbackEndpoints:
    async def test_record_and_read_back(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        headers = tenant.headers("sales_executive")
        posted = client.post(
            f"{V1}/ai/feedback",
            json={
                "target_type": "email_draft",
                "target_id": str(draft.id),
                "rating": 5,
                "verdict": "helpful",
            },
            headers=headers,
        )
        assert posted.status_code == 201, posted.text

        listed = client.get(f"{V1}/ai/feedback", headers=headers).json()["data"]
        assert len(listed) == 1
        assert listed[0]["rating"] == 5
        assert listed[0]["target_type"] == "email_draft"

    async def test_rating_is_bounded(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        r = client.post(
            f"{V1}/ai/feedback",
            json={"target_type": "email_draft", "target_id": str(draft.id), "rating": 9},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422

    async def test_a_correction_is_accepted_without_a_rating(self, client, db, tenant):
        """The only feedback that yields a supervised training pair."""

        draft = await seed_draft(db, tenant)
        r = client.post(
            f"{V1}/ai/feedback",
            json={
                "target_type": "email_draft",
                "target_id": str(draft.id),
                "correction": "should have mentioned pricing",
            },
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 201, r.text

    async def test_unknown_target_is_404(self, client, tenant):
        import uuid as _uuid

        r = client.post(
            f"{V1}/ai/feedback",
            json={"target_type": "email_draft", "target_id": str(_uuid.uuid4()), "rating": 5},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "FEEDBACK_TARGET_NOT_FOUND"

    async def test_marketing_can_rate_a_draft_it_can_see(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        r = client.post(
            f"{V1}/ai/feedback",
            json={"target_type": "email_draft", "target_id": str(draft.id), "rating": 4},
            headers=tenant.headers("marketing"),
        )
        assert r.status_code == 201, r.text

    async def test_an_unassigned_executive_sees_no_feedback(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        client.post(
            f"{V1}/ai/feedback",
            json={"target_type": "email_draft", "target_id": str(draft.id), "rating": 5},
            headers=tenant.headers("sales_executive"),
        )
        listed = client.get(
            f"{V1}/ai/feedback", headers=tenant.headers("sales_executive_2")
        ).json()["data"]
        assert listed == []

    def test_quality_panel_is_leadership_only(self, client, tenant):
        assert (
            client.get(f"{V1}/ai/quality", headers=tenant.headers("sales_executive")).status_code
            == 403
        )

    def test_quality_panel_reports_unavailable_metrics_honestly(self, client, tenant):
        data = client.get(f"{V1}/ai/quality", headers=tenant.headers("admin")).json()["data"]
        assert data["metrics"]["outreach_acceptance"]["available"] is False
        assert data["metrics"]["outreach_acceptance"]["unavailable_reason"]
        assert data["retraining_readiness"]
        assert MIN_SAMPLE_FOR_DISPLAY > 1
