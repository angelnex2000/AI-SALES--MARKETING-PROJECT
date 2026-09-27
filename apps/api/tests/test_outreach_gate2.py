"""Gate 2 — the product's central constraint.

No AI-written email reaches a customer without a human approving *that exact
text*. Approval is therefore bound to content, not to the row: editing an
approved draft voids the approval.
"""

import pytest
from sqlalchemy import text

from app.models.outreach import DraftStatus, EmailDraft

V1 = "/api/v1/outreach"


@pytest.fixture
async def draft(db, tenant):
    row = EmailDraft(
        company_id=tenant.company_id,
        lead_id=tenant.lead_id,
        contact_id=tenant.contact_id,
        subject="Intro",
        body="Original AI-written body",
        explanation="grounded in case study #4",
        ai_generated=True,
        status=DraftStatus.PENDING_APPROVAL,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


class TestWhoMayAct:
    @pytest.mark.parametrize("role", ["marketing", "admin", "sales_manager"])
    def test_only_a_sales_executive_may_approve(self, client, tenant, draft, role):
        r = client.post(f"{V1}/drafts/{draft.id}/approve", headers=tenant.headers(role))
        assert r.status_code == 403

    @pytest.mark.parametrize("role", ["marketing", "admin", "sales_manager"])
    def test_only_a_sales_executive_may_send(self, client, tenant, draft, role):
        r = client.post(f"{V1}/drafts/{draft.id}/send", headers=tenant.headers(role))
        assert r.status_code == 403


class TestApprovalIsRequired:
    def test_unapproved_draft_cannot_be_sent(self, client, tenant, draft):
        r = client.post(f"{V1}/drafts/{draft.id}/send", headers=tenant.headers("sales_executive"))
        assert r.status_code == 422
        assert r.json()["error_code"] == "DRAFT_NOT_APPROVED"

    def test_approved_draft_sends(self, client, tenant, draft):
        client.post(f"{V1}/drafts/{draft.id}/approve", headers=tenant.headers("sales_executive"))
        r = client.post(f"{V1}/drafts/{draft.id}/send", headers=tenant.headers("sales_executive"))
        assert r.status_code == 200, r.text


class TestEditVoidsApproval:
    """The bypass this guard exists for: Marketing legitimately holds
    draft-edit rights, so without it they could rewrite the body after a Sales
    Executive approved it and the send would deliver unapproved text."""

    def test_editing_an_approved_draft_returns_it_to_pending(self, client, tenant, draft):
        client.post(f"{V1}/drafts/{draft.id}/approve", headers=tenant.headers("sales_executive"))
        r = client.put(
            f"{V1}/drafts/{draft.id}",
            json={"body": "Text nobody approved"},
            headers=tenant.headers("marketing"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "pending_approval"
        assert "approval was voided" in r.json()["message"]

    def test_edited_draft_can_no_longer_be_sent(self, client, tenant, draft):
        client.post(f"{V1}/drafts/{draft.id}/approve", headers=tenant.headers("sales_executive"))
        client.put(
            f"{V1}/drafts/{draft.id}",
            json={"body": "Text nobody approved"},
            headers=tenant.headers("marketing"),
        )
        r = client.post(f"{V1}/drafts/{draft.id}/send", headers=tenant.headers("sales_executive"))
        assert r.status_code == 422, "an edited draft must be re-approved first"


class TestSentIsTerminal:
    @pytest.fixture
    def sent_draft(self, client, tenant, draft):
        client.post(f"{V1}/drafts/{draft.id}/approve", headers=tenant.headers("sales_executive"))
        client.post(f"{V1}/drafts/{draft.id}/send", headers=tenant.headers("sales_executive"))
        return draft

    def test_cannot_send_twice(self, client, tenant, sent_draft):
        """A duplicate send means the customer receives the email twice and
        sent_emails double-counts."""

        r = client.post(f"{V1}/drafts/{sent_draft.id}/send", headers=tenant.headers("sales_executive"))
        assert r.status_code == 422
        assert r.json()["error_code"] == "DRAFT_ALREADY_SENT"

    def test_cannot_re_approve(self, client, tenant, sent_draft):
        r = client.post(f"{V1}/drafts/{sent_draft.id}/approve", headers=tenant.headers("sales_executive"))
        assert r.status_code == 422

    def test_cannot_edit(self, client, tenant, sent_draft):
        r = client.put(
            f"{V1}/drafts/{sent_draft.id}",
            json={"body": "rewriting history"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422

    async def test_exactly_one_sent_email_row(self, client, tenant, sent_draft, db):
        client.post(f"{V1}/drafts/{sent_draft.id}/send", headers=tenant.headers("sales_executive"))
        count = (await db.execute(text("SELECT count(*) FROM sent_emails"))).scalar()
        assert count == 1

    async def test_send_lands_on_the_lead_timeline(self, client, tenant, sent_draft, db):
        rows = (
            await db.execute(text("SELECT activity_type FROM crm_activities"))
        ).scalars().all()
        assert "email_sent" in rows, "the Timeline tab must not omit the send"


class TestDraftVisibility:
    """Drafts inherit visibility from the parent lead. The list endpoints
    previously filtered on company_id alone, leaking every rep's drafts."""

    def test_exec_sees_only_drafts_for_their_own_leads(self, client, tenant, draft):
        r = client.get(f"{V1}/drafts", headers=tenant.headers("sales_executive"))
        assert [d["id"] for d in r.json()["data"]] == [str(draft.id)]

    def test_other_exec_sees_none(self, client, tenant, draft):
        r = client.get(f"{V1}/drafts", headers=tenant.headers("sales_executive_2"))
        assert r.json()["data"] == []

    def test_other_exec_cannot_open_the_draft(self, client, tenant, draft):
        r = client.get(f"{V1}/drafts/{draft.id}", headers=tenant.headers("sales_executive_2"))
        assert r.status_code == 404


class TestReplyWebhookHardening:
    """Unauthenticated and internet-facing: malformed input must never 500."""

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"content": "not json"},
            {"json": ["a", "list"]},
            {"json": {"sent_email_id": "not-a-uuid"}},
            {"json": {}},
        ],
    )
    def test_malformed_payloads_are_422(self, client, kwargs):
        r = client.post(f"{V1}/replies/webhook", **kwargs)
        assert r.status_code == 422, r.text
