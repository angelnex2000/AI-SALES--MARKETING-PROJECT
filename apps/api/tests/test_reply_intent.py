"""Reply Intent Agent — preprocessing, negation, precedence, persistence, API.

The rule under test throughout: a reply is a person answering *us*, so the
text arrives wrapped in our own words and the most common way to answer is to
name the thing being declined. Both make keyword matching wrong by default.
"""

import pytest
from sqlalchemy import text

from agents.reply_intent.agent import (
    MAX_CONFIDENCE,
    MIN_ACTIONABLE_CONFIDENCE,
    MODEL_VERSION,
    ReplyIntentAgent,
)
from agents.reply_intent.labels import ACTION_FOR_INTENT, ReplyIntent, SuggestedAction
from agents.reply_intent.preprocess import clean_reply
from agents.reply_intent.rules import RULES, is_negated_at

V1 = "/api/v1"


async def classify(body: str) -> dict:
    return await ReplyIntentAgent().run({"reply_text": body})


# The email our outreach agent sent. Every reply below quotes it, because that
# is what an email client does.
OUR_PITCH = (
    "Hi Ravi, would you be open to a quick demo next week? Happy to share "
    "pricing too - just let me know a time that works and I'll send a calendar "
    "invite."
)


class TestQuotedThread:
    """The failure that makes a keyword classifier read its own outbox.

    A bare "No thanks." arrives with our pitch quoted underneath. Classify the
    whole body and `demo`, `pricing`, `calendar` and `let me know a time` all
    fire — a flat refusal becomes a booking at high confidence.
    """

    async def test_refusal_is_not_read_as_the_pitch_it_quotes(self):
        out = await classify(
            f"No thanks.\n\n"
            f"On Tue, 4 Aug 2026 at 09:12, Priya <priya@acme.com> wrote:\n> {OUR_PITCH}"
        )
        assert out["intent"] == ReplyIntent.NOT_INTERESTED.value
        assert out["suggested_action"] == SuggestedAction.MARK_CLOSED_LOST.value

    async def test_outlook_original_message_marker(self):
        out = await classify(
            f"Not for us at the moment.\n\n"
            f"-----Original Message-----\nFrom: Priya\nSent: Tuesday\n\n{OUR_PITCH}"
        )
        assert out["intent"] != ReplyIntent.MEETING_REQUEST.value

    async def test_outlook_header_block_marker(self):
        out = await classify(f"Please send more information.\n\nFrom: Priya\nSent: Tue\n\n{OUR_PITCH}")
        assert out["intent"] == ReplyIntent.INTERESTED.value

    async def test_bare_angle_quoting_without_a_header(self):
        assert OUR_PITCH not in clean_reply(f"Sure.\n> {OUR_PITCH}\n> {OUR_PITCH}")

    async def test_mobile_signature_is_removed(self):
        assert clean_reply("Not interested.\n\nSent from my iPhone") == "Not interested."

    async def test_confidentiality_footer_is_removed(self):
        """The standard wording is "if you have received this in error please
        call the sender", which fires the meeting rules on boilerplate."""

        out = await classify(
            "Please remove me from your list.\n\n"
            "This email and any attachments are confidential. If you have received "
            "this in error please call the sender and delete it."
        )
        assert out["intent"] == ReplyIntent.UNSUBSCRIBE.value

    async def test_quote_only_reply_reports_emptiness_not_low_confidence(self):
        """"They wrote nothing we can read" and "they wrote something we could
        not interpret" call for different handling by the rep."""

        out = await classify(f"On Tue, Priya <p@acme.com> wrote:\n> {OUR_PITCH}")
        assert out["intent"] == ReplyIntent.UNKNOWN.value
        assert "no new text" in out["explanation"]
        assert out["matched_phrase"] is None

    async def test_cleaned_text_is_reported_for_debugging(self):
        out = await classify(f"Sounds good.\n\nOn Tue, Priya wrote:\n> {OUR_PITCH}")
        assert out["cleaned_text"] == "Sounds good."


class TestOutOfOffice:
    """An absence notice is not a reply, and its body is full of other
    people's contact details."""

    async def test_auto_reply_is_not_a_meeting_request(self):
        out = await classify(
            "I am out of office until 15 March with limited access to email. "
            "For urgent matters call Priya on 9988776655."
        )
        assert out["intent"] == ReplyIntent.OUT_OF_OFFICE.value
        assert out["suggested_action"] == SuggestedAction.NO_ACTION.value

    async def test_no_alternatives_are_offered_from_an_autoresponder(self):
        """Otherwise the UI puts a Schedule Meeting button on an absence
        notice, sourced from "for urgent matters call"."""

        out = await classify("Automatic reply: I'm on annual leave. Please call the main desk.")
        assert out["alternatives"] == []
        assert "autoresponder" in out["explanation"]

    @pytest.mark.parametrize(
        "body",
        [
            "I am currently on vacation and will return on Monday.",
            "Automatic reply: away from my desk until Thursday.",
            "I'm travelling this week with limited access to my email.",
            "Thanks for your note - I am on maternity leave until October.",
        ],
    )
    async def test_common_autoresponder_phrasings(self, body):
        assert (await classify(body))["intent"] == ReplyIntent.OUT_OF_OFFICE.value


class TestUnsubscribe:
    """Asymmetric costs: suppressing one lead in error costs a lead; emailing
    someone who asked us to stop is a compliance matter."""

    @pytest.mark.parametrize(
        "body",
        [
            "Please unsubscribe me.",
            "Remove me from your mailing list.",
            "Stop emailing me.",
            "Do not contact me again.",
            "Please opt-out this address.",
        ],
    )
    async def test_opt_out_phrasings(self, body):
        out = await classify(body)
        assert out["intent"] == ReplyIntent.UNSUBSCRIBE.value
        assert out["suggested_action"] == SuggestedAction.DO_NOT_CONTACT.value

    async def test_opt_out_outranks_a_warm_reply(self):
        out = await classify(
            "This looks interesting and I'd love a demo, but please unsubscribe "
            "this address and use my personal one."
        )
        assert out["intent"] == ReplyIntent.UNSUBSCRIBE.value
        assert "overridden" in out["explanation"]

    def test_opt_out_action_is_never_degraded_by_low_confidence(self):
        """Every other label falls back to manual review below the threshold.
        Downgrading an opt-out is the one degradation with a legal cost."""

        agent = ReplyIntentAgent()
        assert agent._action(ReplyIntent.UNSUBSCRIBE, 0.01) is SuggestedAction.DO_NOT_CONTACT
        assert agent._action(ReplyIntent.NOT_INTERESTED, 0.01) is SuggestedAction.MANUAL_REVIEW


class TestNegation:
    """A reply names the thing it is declining."""

    @pytest.mark.parametrize(
        "body",
        [
            "We're not looking for a demo right now.",
            "We don't need a demo, thanks.",
            "No demo required.",
        ],
    )
    async def test_declined_meeting_is_not_a_meeting_request(self, body):
        out = await classify(body)
        assert out["intent"] != ReplyIntent.MEETING_REQUEST.value
        assert out["suggested_action"] != SuggestedAction.SCHEDULE_MEETING.value

    async def test_declined_pricing_is_not_a_pricing_request(self):
        out = await classify("I don't need pricing - we have already chosen a vendor.")
        assert out["intent"] == ReplyIntent.NOT_INTERESTED.value

    async def test_a_negator_does_not_reach_across_a_clause_boundary(self):
        """"I'm not sure I follow, but let's book a demo" is a booking. A
        window-only negation check reads it as a refusal."""

        out = await classify("I'm not sure I follow, but let's book a demo.")
        assert out["intent"] == ReplyIntent.MEETING_REQUEST.value

    async def test_a_rule_keeps_looking_past_a_negated_hit(self):
        out = await classify("We don't need a demo, but can you send your calendar?")
        assert out["intent"] == ReplyIntent.MEETING_REQUEST.value

    async def test_unknown_explains_which_phrase_was_suppressed(self):
        """A blank result with no reason reads as a broken agent."""

        out = await classify("Whatever you do, no demo.")
        if out["intent"] == ReplyIntent.UNKNOWN.value:
            assert "negated clause" in out["explanation"]

    def test_negation_helper_respects_clause_boundaries(self):
        assert is_negated_at("we don't need a demo", len("we don't need a "))
        assert not is_negated_at("not sure, but book a demo", len("not sure, but book a "))

    def test_phrases_that_contain_a_negator_are_not_self_suppressed(self):
        """"not interested" and "not right now" would delete their own rules."""

        for rule in RULES:
            if rule.intent in (ReplyIntent.NOT_INTERESTED, ReplyIntent.FOLLOW_UP_LATER):
                assert not rule.negatable


class TestWordBoundaries:
    @pytest.mark.parametrize(
        "body",
        [
            "Apologies, I recalled that message.",
            "That approach looks costly to maintain.",
        ],
    )
    async def test_substrings_do_not_match(self, body):
        out = await classify(body)
        assert out["intent"] == ReplyIntent.UNKNOWN.value, f"{body!r} matched on a substring"

    async def test_real_words_still_match(self):
        assert (await classify("What is the cost?"))["intent"] == ReplyIntent.PRICING_REQUEST.value


class TestModuleBriefExamples:
    """The worked examples from the Module 10 brief."""

    @pytest.mark.parametrize(
        "body,expected",
        [
            ("Can we schedule a demo next Tuesday?", ReplyIntent.MEETING_REQUEST),
            ("Book a demo", ReplyIntent.MEETING_REQUEST),
            ("What is the pricing?", ReplyIntent.PRICING_REQUEST),
            ("Send me pricing first.", ReplyIntent.PRICING_REQUEST),
            ("Not interested", ReplyIntent.NOT_INTERESTED),
            ("Reach out next month", ReplyIntent.FOLLOW_UP_LATER),
            ("Contact me next month.", ReplyIntent.FOLLOW_UP_LATER),
            ("Sure, let's schedule a demo.", ReplyIntent.MEETING_REQUEST),
        ],
    )
    async def test_expected_label(self, body, expected):
        assert (await classify(body))["intent"] == expected.value

    async def test_suggested_action_matches_the_label(self):
        out = await classify("Can we schedule a demo next Tuesday?")
        assert out["suggested_action"] == SuggestedAction.SCHEDULE_MEETING.value


class TestConfidence:
    async def test_a_keyword_match_never_reports_near_certainty(self):
        """The brief's example returns 0.97 for a regex hit. This number sits
        beside a button a rep is invited to press."""

        for body in ("Book a demo", "Please unsubscribe me", "What is the pricing?"):
            assert (await classify(body))["confidence"] <= MAX_CONFIDENCE

    def test_no_rule_is_configured_above_the_cap(self):
        assert all(0.0 < rule.base_confidence <= MAX_CONFIDENCE for rule in RULES)

    async def test_multiple_intents_lower_confidence(self):
        single = await classify("What is the pricing?")
        multi = await classify("Sounds great - what does it cost, and can we talk Thursday?")
        assert multi["confidence"] < single["confidence"]

    async def test_multiple_intents_are_reported_not_discarded(self):
        """"Send pricing before we book a demo" asks for two things; one label
        drops half of what the customer said."""

        out = await classify("Could you send pricing before we book a demo?")
        labels = {out["intent"]} | {a["intent"] for a in out["alternatives"]}
        assert {
            ReplyIntent.MEETING_REQUEST.value,
            ReplyIntent.PRICING_REQUEST.value,
        } <= labels
        assert all("suggested_action" in a for a in out["alternatives"])

    async def test_below_threshold_confidence_degrades_to_manual_review(self):
        out = await classify("Sounds interesting. Might revisit next quarter.")
        if out["confidence"] < MIN_ACTIONABLE_CONFIDENCE:
            assert out["suggested_action"] == SuggestedAction.MANUAL_REVIEW.value

    async def test_unknown_routes_to_a_human(self):
        out = await classify("Ok.")
        assert out["intent"] == ReplyIntent.UNKNOWN.value
        assert out["suggested_action"] == SuggestedAction.MANUAL_REVIEW.value

    async def test_model_version_is_reported(self):
        assert (await classify("Book a demo"))["model_version"] == MODEL_VERSION


class TestTaxonomy:
    def test_every_intent_has_an_action(self):
        assert set(ACTION_FOR_INTENT) == set(ReplyIntent)

    def test_enum_values_are_lowercase_names(self):
        """`Base.type_annotation_map` persists enums by value; the migration
        and the API contract both assume this holds."""

        assert all(member.value == member.name.lower() for member in ReplyIntent)


# --------------------------------------------------------------------- wiring


async def seed_reply(db, tenant, body: str):
    from app.models.outreach import DraftStatus, EmailDraft, Reply, SentEmail

    draft = EmailDraft(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        subject="Quick question",
        body=OUR_PITCH,
        explanation="seed",
        status=DraftStatus.SENT,
    )
    db.add(draft)
    await db.flush()
    from datetime import UTC, datetime

    sent = SentEmail(
        company_id=tenant.company_id,
        draft_id=draft.id,
        lead_id=tenant.lead_id,
        sent_at=datetime.now(UTC),
    )
    db.add(sent)
    await db.flush()
    reply = Reply(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        sent_email_id=sent.id,
        body=body,
    )
    db.add(reply)
    await db.commit()
    return reply, sent


async def run_classification(db, tenant, body: str):
    from app.models.job import Job, JobStatus
    from app.services.ai_orchestrator import AIOrchestrator

    reply, _ = await seed_reply(db, tenant, body)
    job = Job(
        company_id=tenant.company_id,
        job_type="reply_intent",
        lead_id=tenant.lead_id,
        created_by_user_id=tenant.exec_id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await AIOrchestrator(db).classify_reply(reply=reply, job=job)
    return reply, job


class TestPersistence:
    async def test_result_row_carries_its_reasoning(self, db, tenant):
        await run_classification(db, tenant, "Can we schedule a demo next Tuesday?")
        row = (
            await db.execute(
                text(
                    "SELECT intent, confidence, suggested_action, explanation, "
                    "matched_phrase, model_version FROM reply_intent_results"
                )
            )
        ).one()
        assert row[0] == ReplyIntent.MEETING_REQUEST.value
        assert row[2] == SuggestedAction.SCHEDULE_MEETING.value
        assert row[3], "explanation is what makes a suggested action reviewable"
        assert "demo" in row[4].lower()

    async def test_classification_appears_on_the_timeline(self, db, tenant):
        await run_classification(db, tenant, "What is the pricing?")
        rows = (
            await db.execute(text("SELECT activity_type, description FROM crm_activities"))
        ).all()
        assert any(r[0] == "reply_classified" for r in rows)
        assert any("pricing_request" in r[1] for r in rows)

    async def test_opt_out_gets_its_own_activity_type(self, db, tenant):
        """Findable in the timeline without reading every classification
        event — it is the one outcome with a compliance deadline."""

        await run_classification(db, tenant, "Please remove me from your list.")
        kinds = [
            r[0] for r in (await db.execute(text("SELECT activity_type FROM crm_activities"))).all()
        ]
        assert "reply_opt_out" in kinds

    async def test_classification_never_moves_the_lead_itself(self, db, tenant):
        """The brief's workflow has "CRM Status Updated" follow classification
        automatically. A lead auto-closed by a regex reading of someone's
        phrasing disappears from every list a rep works from, with no prompt
        that a decision was made."""

        from app.models.lead import Lead, LeadStatus

        await run_classification(db, tenant, "Not interested, we went with another vendor.")
        lead = await db.get(Lead, tenant.lead_id)
        await db.refresh(lead)
        assert lead.status == LeadStatus.NEW

        intent = (await db.execute(text("SELECT intent FROM reply_intent_results"))).scalar()
        assert intent == ReplyIntent.NOT_INTERESTED.value, "the suggestion is still recorded"

    async def test_job_completes_with_the_outcome(self, db, tenant):
        from app.models.job import JobStatus

        _, job = await run_classification(db, tenant, "Book a demo")
        assert job.status == JobStatus.COMPLETED
        assert job.result["intent"] == ReplyIntent.MEETING_REQUEST.value
        assert job.completed_at is not None

    async def test_agent_io_is_logged_for_debugging(self, db, tenant):
        await run_classification(db, tenant, "Book a demo")
        agents = [
            r[0]
            for r in (await db.execute(text("SELECT agent_name FROM ai_interaction_logs"))).all()
        ]
        assert "reply_intent" in agents

    async def test_reclassification_appends_rather_than_replaces(self, db, tenant):
        from app.models.job import Job, JobStatus
        from app.services.ai_orchestrator import AIOrchestrator

        reply, _ = await run_classification(db, tenant, "Book a demo")
        job = Job(
            company_id=tenant.company_id,
            job_type="reply_intent",
            lead_id=tenant.lead_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).classify_reply(reply=reply, job=job)

        count = (await db.execute(text("SELECT count(*) FROM reply_intent_results"))).scalar()
        assert count == 2, "AI output is append-only history"


class _FakeTask:
    def __init__(self):
        self.calls: list[tuple] = []

    def delay(self, *args):
        self.calls.append(args)


class _DeadTask:
    def delay(self, *args):
        raise ConnectionError("broker unreachable")


@pytest.fixture
def fake_task(monkeypatch):
    task = _FakeTask()
    monkeypatch.setattr("app.routers.ai.run_reply_intent", task)
    monkeypatch.setattr("app.routers.outreach.run_reply_intent", task)
    return task


class TestClassifyEndpoint:
    async def test_dispatches_with_the_reply_id(self, client, db, tenant, fake_task):
        reply, _ = await seed_reply(db, tenant, "Book a demo")
        r = client.post(
            f"{V1}/ai/replies/{reply.id}/classify", headers=tenant.headers("sales_executive")
        )
        assert r.status_code in (200, 202), r.text
        assert fake_task.calls[0][1] == str(reply.id)

    async def test_two_replies_on_one_lead_both_classify(self, client, db, tenant, fake_task):
        """Per-lead job dedupe would attach the second reply to the first
        reply's in-flight job and never read it — silently dropping a
        customer's message."""

        first, _ = await seed_reply(db, tenant, "What is the pricing?")
        second, _ = await seed_reply(db, tenant, "Actually, can we book a demo?")
        for reply in (first, second):
            client.post(
                f"{V1}/ai/replies/{reply.id}/classify", headers=tenant.headers("sales_executive")
            )
        dispatched = {call[1] for call in fake_task.calls}
        assert dispatched == {str(first.id), str(second.id)}

    async def test_cross_tenant_reply_is_404(self, client, db, tenant, other_tenant, fake_task):
        reply, _ = await seed_reply(db, other_tenant, "Book a demo")
        r = client.post(
            f"{V1}/ai/replies/{reply.id}/classify", headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "REPLY_NOT_FOUND"

    async def test_unassigned_executive_is_404(self, client, db, tenant, fake_task):
        """Isolation answers before anything else — the second rep must not
        learn the reply exists."""

        reply, _ = await seed_reply(db, tenant, "Book a demo")
        r = client.post(
            f"{V1}/ai/replies/{reply.id}/classify",
            headers=tenant.headers("sales_executive_2"),
        )
        assert r.status_code == 404


class TestReadEndpoints:
    async def test_latest_classification_is_returned(self, client, db, tenant):
        reply, _ = await run_classification(db, tenant, "Can we schedule a demo next Tuesday?")
        r = client.get(
            f"{V1}/ai/replies/{reply.id}/intent", headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["intent"] == ReplyIntent.MEETING_REQUEST.value
        assert data["explanation"]
        assert data["matched_phrase"]

    async def test_unclassified_reply_is_404_not_an_empty_guess(self, client, db, tenant):
        reply, _ = await seed_reply(db, tenant, "Book a demo")
        r = client.get(
            f"{V1}/ai/replies/{reply.id}/intent", headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "NO_REPLY_INTENT"

    async def test_lead_view_collapses_to_one_row_per_reply(self, client, db, tenant):
        from app.models.job import Job, JobStatus
        from app.services.ai_orchestrator import AIOrchestrator

        reply, _ = await run_classification(db, tenant, "Book a demo")
        job = Job(
            company_id=tenant.company_id,
            job_type="reply_intent",
            lead_id=tenant.lead_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).classify_reply(reply=reply, job=job)

        headers = tenant.headers("sales_executive")
        current = client.get(f"{V1}/ai/leads/{tenant.lead_id}/reply-intents", headers=headers)
        full = client.get(
            f"{V1}/ai/leads/{tenant.lead_id}/reply-intents?history=true", headers=headers
        )
        assert len(current.json()["data"]) == 1, "a rep must not see the same reply twice"
        assert len(full.json()["data"]) == 2

    async def test_cross_tenant_read_is_404(self, client, db, tenant, other_tenant):
        reply, _ = await run_classification(db, other_tenant, "Book a demo")
        r = client.get(
            f"{V1}/ai/replies/{reply.id}/intent", headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 404


class TestWebhookDispatch:
    async def test_inbound_reply_is_queued_for_classification(self, client, db, tenant, fake_task):
        """The webhook previously created a Job it never dispatched, so every
        inbound reply sat `pending` forever."""

        _, sent = await seed_reply(db, tenant, "seed")
        r = client.post(
            f"{V1}/outreach/replies/webhook",
            json={"sent_email_id": str(sent.id), "body": "Can we book a demo?"},
        )
        assert r.status_code == 202, r.text
        assert len(fake_task.calls) == 1

    async def test_dead_broker_does_not_make_the_provider_retry(
        self, client, db, tenant, monkeypatch
    ):
        """A 503 here means the provider redelivers and the customer's message
        is stored twice. The Reply is already committed and the job is marked
        failed, so re-running is possible without duplication."""

        monkeypatch.setattr("app.routers.outreach.run_reply_intent", _DeadTask())
        _, sent = await seed_reply(db, tenant, "seed")
        r = client.post(
            f"{V1}/outreach/replies/webhook",
            json={"sent_email_id": str(sent.id), "body": "Not interested."},
        )
        assert r.status_code == 202, r.text

        statuses = [
            row[0]
            for row in (
                await db.execute(text("SELECT status FROM jobs WHERE job_type='reply_intent'"))
            ).all()
        ]
        assert "failed" in statuses, "a stuck `pending` job is a spinner nobody can clear"
