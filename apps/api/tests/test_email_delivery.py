"""Email delivery and contact suppression.

Sending is the one thing in this product that cannot be undone. So the tests
here are mostly about refusals: what must not go out, and what must never be
recorded as having gone out when it did not.
"""

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text

from app.models.outreach import DraftStatus, EmailDraft
from app.services import email_service, outreach_service

V1 = "/api/v1"


async def seed_draft(db, tenant, *, contact_id=..., status=DraftStatus.APPROVED):
    draft = EmailDraft(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        contact_id=tenant.contact_id if contact_id is ... else contact_id,
        subject="Quick question about telemedicine",
        body="Hi there — worth a short conversation?",
        explanation="seed",
        ai_generated=True,
        status=status,
        approved_by_id=tenant.exec_id if status is DraftStatus.APPROVED else None,
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)
    return draft


def send(client, tenant, draft):
    return client.post(
        f"{V1}/outreach/drafts/{draft.id}/send", headers=tenant.headers("sales_executive")
    )


class TestDryRunDefault:
    """Credentials being present is not consent to email prospects."""

    async def test_nothing_is_transmitted_by_default(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        with patch("smtplib.SMTP") as smtp:
            assert send(client, tenant, draft).status_code == 200
        smtp.assert_not_called(), "no SMTP connection may be opened in dry-run"

    async def test_the_row_says_it_was_not_delivered(self, client, db, tenant):
        """The easiest mistake on a first real send is assuming the pipeline
        worked because the row appeared."""

        draft = await seed_draft(db, tenant)
        send(client, tenant, draft)
        row = (
            await db.execute(text("SELECT delivery_status, to_address FROM sent_emails"))
        ).one()
        assert row[0] == "dry_run"
        assert row[1] == "primary@acme.example.com"

    async def test_the_gate_2_state_machine_still_runs(self, client, db, tenant):
        """Dry-run must exercise the real path, or it proves nothing."""

        draft = await seed_draft(db, tenant)
        send(client, tenant, draft)
        await db.refresh(draft)
        assert draft.status == DraftStatus.SENT

    async def test_the_timeline_says_it_was_not_transmitted(self, client, db, tenant):
        draft = await seed_draft(db, tenant)
        send(client, tenant, draft)
        descriptions = [
            r[0]
            for r in (
                await db.execute(
                    text("SELECT description FROM crm_activities WHERE activity_type='email_sent'")
                )
            ).all()
        ]
        assert descriptions and "not transmitted" in descriptions[0]


class TestSuppression:
    """An approved draft is the *sender's* sign-off. It is not consent from the
    recipient, and this is the only place the two are reconciled."""

    async def test_a_suppressed_contact_is_refused(self, client, db, tenant):
        from app.models.lead import Contact

        contact = await db.get(Contact, tenant.contact_id)
        contact.do_not_contact = True
        contact.do_not_contact_reason = "reply_intent:unsubscribe"
        await db.commit()

        draft = await seed_draft(db, tenant)
        r = send(client, tenant, draft)
        assert r.status_code == 422
        assert r.json()["error_code"] == "CONTACT_DO_NOT_CONTACT"

    async def test_a_refused_send_writes_no_sent_email(self, client, db, tenant):
        from app.models.lead import Contact

        contact = await db.get(Contact, tenant.contact_id)
        contact.do_not_contact = True
        await db.commit()

        draft = await seed_draft(db, tenant)
        send(client, tenant, draft)
        count = (await db.execute(text("SELECT count(*) FROM sent_emails"))).scalar()
        assert count == 0

    async def test_a_refused_send_leaves_the_draft_approved(self, client, db, tenant):
        """Not `sent` — nothing was sent, and marking it so would make the
        terminal-state guard block a legitimate retry to a different contact."""

        from app.models.lead import Contact

        contact = await db.get(Contact, tenant.contact_id)
        contact.do_not_contact = True
        await db.commit()

        draft = await seed_draft(db, tenant)
        send(client, tenant, draft)
        await db.refresh(draft)
        assert draft.status == DraftStatus.APPROVED

    async def test_suppression_is_idempotent(self, db, tenant):
        """The first opt-out keeps its timestamp — that is the date that
        answers 'when did they ask?'."""

        from app.models.lead import Contact

        contact = await db.get(Contact, tenant.contact_id)
        await outreach_service.suppress_contact(db, contact=contact, reason="first")
        await db.commit()
        first_at = contact.do_not_contact_at

        await outreach_service.suppress_contact(db, contact=contact, reason="second")
        await db.commit()
        assert contact.do_not_contact_at == first_at
        assert contact.do_not_contact_reason == "first"


class TestUnsubscribeClosesTheLoop:
    """Module 10 could classify an opt-out but nothing could act on it."""

    async def _classify(self, db, tenant, body: str):
        from datetime import UTC, datetime

        from app.models.job import Job, JobStatus
        from app.models.outreach import Reply, SentEmail
        from app.services.ai_orchestrator import AIOrchestrator

        draft = await seed_draft(db, tenant, status=DraftStatus.SENT)
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
        job = Job(
            company_id=tenant.company_id,
            job_type="reply_intent",
            lead_id=tenant.lead_id,
            status=JobStatus.PENDING,
        )
        db.add(job)
        await db.commit()
        await AIOrchestrator(db).classify_reply(reply=reply, job=job)
        return reply

    async def test_an_unsubscribe_reply_suppresses_the_contact(self, db, tenant):
        from app.models.lead import Contact

        await self._classify(db, tenant, "Please remove me from your list.")
        contact = await db.get(Contact, tenant.contact_id)
        await db.refresh(contact)
        assert contact.do_not_contact is True
        assert contact.do_not_contact_reason == "reply_intent:unsubscribe"

    async def test_an_ordinary_reply_suppresses_nobody(self, db, tenant):
        from app.models.lead import Contact

        await self._classify(db, tenant, "Can we schedule a demo next Tuesday?")
        contact = await db.get(Contact, tenant.contact_id)
        await db.refresh(contact)
        assert contact.do_not_contact is False

    async def test_a_suppressed_contact_then_blocks_the_next_send(self, client, db, tenant):
        """The end-to-end property that matters: classify → suppress → refuse."""

        await self._classify(db, tenant, "Unsubscribe me please.")
        draft = await seed_draft(db, tenant)
        r = send(client, tenant, draft)
        assert r.status_code == 422
        assert r.json()["error_code"] == "CONTACT_DO_NOT_CONTACT"


class TestUnsendableDrafts:
    async def test_a_draft_with_no_contact_is_refused(self, client, db, tenant):
        draft = await seed_draft(db, tenant, contact_id=None)
        r = send(client, tenant, draft)
        assert r.status_code == 422
        assert r.json()["error_code"] == "DRAFT_HAS_NO_CONTACT"

    async def test_a_contact_with_no_address_is_refused(self, client, db, tenant):
        from app.models.lead import Contact

        contact = await db.get(Contact, tenant.contact_id)
        contact.email = None
        await db.commit()

        draft = await seed_draft(db, tenant)
        r = send(client, tenant, draft)
        assert r.status_code == 422
        assert r.json()["error_code"] == "CONTACT_HAS_NO_EMAIL"


class TestLiveSending:
    @pytest.fixture
    def live(self, monkeypatch):
        monkeypatch.setattr(email_service.settings, "EMAIL_SEND_ENABLED", True)
        monkeypatch.setattr(email_service.settings, "SMTP_HOST", "in-v3.mailjet.com")
        monkeypatch.setattr(email_service.settings, "SMTP_USER", "key")
        monkeypatch.setattr(email_service.settings, "SMTP_PASSWORD", "secret")
        monkeypatch.setattr(email_service.settings, "EMAIL_FROM_ADDRESS", "sales@example.com")

    def test_a_message_is_handed_to_the_relay(self, live):
        with patch("smtplib.SMTP") as smtp:
            smtp.return_value.__enter__.return_value = MagicMock()
            result = email_service.send(
                to_address="ravi@medcare.example.com", subject="Hi", body="Body"
            )
        assert result.status == email_service.STATUS_SENT
        assert result.provider_message_id

    def test_the_connection_is_encrypted_before_the_secret_is_sent(self, live):
        """The SMTP password here is the Mailjet secret key; on port 587 it
        would otherwise cross the network in the clear."""

        with patch("smtplib.SMTP") as smtp:
            connection = MagicMock()
            smtp.return_value.__enter__.return_value = connection
            email_service.send(to_address="ravi@medcare.example.com", subject="Hi", body="Body")

        assert connection.method_calls[0][0] == "starttls"
        assert connection.method_calls[1][0] == "login"

    def test_a_transport_failure_is_reported_not_raised(self, live):
        with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            result = email_service.send(to_address="a@b.com", subject="s", body="b")
        assert result.status == email_service.STATUS_FAILED
        assert "connection refused" in result.error

    async def test_a_failed_send_keeps_the_draft_approved(self, client, db, tenant, live):
        """The customer never received it, so marking the draft sent would both
        lie to the rep and block the retry."""

        draft = await seed_draft(db, tenant)
        with patch("smtplib.SMTP", side_effect=OSError("relay down")):
            r = send(client, tenant, draft)

        assert r.status_code == 422
        assert r.json()["error_code"] == "EMAIL_DELIVERY_FAILED"
        await db.refresh(draft)
        assert draft.status == DraftStatus.APPROVED

    async def test_a_failed_send_is_still_recorded(self, client, db, tenant, live):
        draft = await seed_draft(db, tenant)
        with patch("smtplib.SMTP", side_effect=OSError("relay down")):
            send(client, tenant, draft)
        row = (
            await db.execute(text("SELECT delivery_status, delivery_error FROM sent_emails"))
        ).one()
        assert row[0] == "failed"
        assert "relay down" in row[1]

    def test_enabling_sending_without_a_validated_sender_is_an_error(self, live, monkeypatch):
        """Rejected before the send is attempted, so it is not discovered after
        a draft has been marked sent."""

        monkeypatch.setattr(email_service.settings, "EMAIL_FROM_ADDRESS", "")
        with pytest.raises(email_service.EmailNotConfiguredError, match="EMAIL_FROM_ADDRESS"):
            email_service.send(to_address="a@b.com", subject="s", body="b")


class TestSecretsAndPII:
    def test_the_config_preview_never_returns_credentials(self):
        preview = email_service.preview_config()
        assert "SMTP_PASSWORD" not in preview
        assert "password" not in {k.lower() for k in preview}
        assert set(preview) == {
            "provider",
            "send_enabled",
            "configured",
            "missing_settings",
            "smtp_host",
            "smtp_port",
            "from_address",
            "from_name",
        }

    def test_recipient_addresses_are_masked_in_logs(self):
        """Recipient addresses are lead PII, and the request middleware already
        refuses to log bodies for the same reason."""

        masked = email_service._mask("ravi.kumar@medcare.example.com")
        assert "ravi.kumar" not in masked
        assert masked.endswith("@medcare.example.com")

    def test_there_is_no_bulk_send_entry_point(self):
        """Every send passes Gate 2 individually; a batch helper would be a way
        around the one control that makes AI-written email safe to deliver."""

        assert not hasattr(email_service, "send_bulk")
