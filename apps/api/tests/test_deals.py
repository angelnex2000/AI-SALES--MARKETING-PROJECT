"""Deals: money precision, stage transitions, feedback-learning outcomes."""

from decimal import Decimal

import pytest
from sqlalchemy import text

V1 = "/api/v1"


@pytest.fixture
def deal(client, tenant):
    r = client.post(
        f"{V1}/deals",
        json={
            "lead_id": str(tenant.lead_id),
            "name": "Chatbot rollout",
            "amount": "800000.10",
            "currency": "inr",
        },
        headers=tenant.headers("sales_manager"),
    )
    assert r.status_code == 201, r.text
    return r.json()["data"]


class TestMoneyPrecision:
    """Deal.amount is NUMERIC, never float: it is summed across a whole
    pipeline to produce revenue forecasts, so float error compounds per deal."""

    def test_amount_round_trips_exactly(self, deal):
        assert Decimal(deal["amount"]) == Decimal("800000.10")

    def test_currency_is_normalised(self, deal):
        assert deal["currency"] == "INR", "usd and USD must not become two buckets"

    def test_sums_are_exact(self, client, tenant, deal):
        for amount in ("0.10", "0.20"):
            client.post(
                f"{V1}/deals",
                json={"lead_id": str(tenant.lead_id), "name": "cents", "amount": amount, "currency": "INR"},
                headers=tenant.headers("sales_manager"),
            )
        board = client.get(f"{V1}/pipeline/board", headers=tenant.headers("sales_manager")).json()["data"]
        new_col = next(c for c in board if c["stage"] == "new")
        assert Decimal(new_col["totals_by_currency"]["INR"]) == Decimal("800000.40")

    def test_totals_are_reported_per_currency(self, client, tenant, deal):
        client.post(
            f"{V1}/deals",
            json={"lead_id": str(tenant.lead_id), "name": "usd deal", "amount": "10.00", "currency": "USD"},
            headers=tenant.headers("sales_manager"),
        )
        board = client.get(f"{V1}/pipeline/board", headers=tenant.headers("sales_manager")).json()["data"]
        new_col = next(c for c in board if c["stage"] == "new")
        assert set(new_col["totals_by_currency"]) == {"INR", "USD"}, "mixing currencies is meaningless"

    @pytest.mark.parametrize("amount", ["-5", "1.234"])
    def test_invalid_amounts_rejected(self, client, tenant, amount):
        r = client.post(
            f"{V1}/deals",
            json={"lead_id": str(tenant.lead_id), "name": "bad", "amount": amount},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 422


class TestStageTransitions:
    """Stage is a business event, not a field edit: it records outcomes and
    refreshes the forecast."""

    def test_stage_cannot_be_changed_via_plain_update(self, client, tenant, deal):
        client.put(
            f"{V1}/deals/{deal['id']}",
            json={"stage": "closed_won"},
            headers=tenant.headers("sales_manager"),
        )
        r = client.get(f"{V1}/deals/{deal['id']}", headers=tenant.headers("sales_manager"))
        assert r.json()["data"]["stage"] == "new"

    def test_closing_lost_requires_a_reason(self, client, tenant, deal):
        """Feedback learning retrains on structured loss reasons; free text or
        a missing reason makes the example unusable."""

        r = client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_lost"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422
        assert r.json()["error_code"] == "LOSS_REASON_REQUIRED"

    def test_unknown_loss_reason_rejected(self, client, tenant, deal):
        r = client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_lost", "loss_reason": "just_because"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 422

    def test_cannot_close_twice(self, client, tenant, deal):
        """A second outcome row would double-count the deal in retraining."""

        body = {"stage": "closed_lost", "loss_reason": "chose_competitor"}
        client.patch(f"{V1}/deals/{deal['id']}/stage", json=body, headers=tenant.headers("sales_executive"))
        r = client.patch(f"{V1}/deals/{deal['id']}/stage", json=body, headers=tenant.headers("sales_executive"))
        assert r.status_code == 422
        assert r.json()["error_code"] == "DEAL_ALREADY_CLOSED"

    def test_exec_cannot_reopen_a_closed_won_deal(self, client, tenant, deal):
        client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_won"},
            headers=tenant.headers("sales_executive"),
        )
        r = client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "negotiation"},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 403, "reopening rewrites recognised revenue"

    def test_manager_can_reopen(self, client, tenant, deal):
        client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_won"},
            headers=tenant.headers("sales_executive"),
        )
        r = client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "negotiation"},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 200, r.text


class TestOutcomesForFeedbackLearning:
    async def test_outcome_is_keyed_to_the_deal(self, client, tenant, deal, db):
        """One lead can hold several opportunities. Keyed by lead_id alone, an
        upsell that won and a renewal that lost were indistinguishable."""

        second = client.post(
            f"{V1}/deals",
            json={"lead_id": str(tenant.lead_id), "name": "Renewal", "amount": "10.00"},
            headers=tenant.headers("sales_manager"),
        ).json()["data"]

        client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_won"},
            headers=tenant.headers("sales_executive"),
        )
        client.patch(
            f"{V1}/deals/{second['id']}/stage",
            json={"stage": "closed_lost", "loss_reason": "timing"},
            headers=tenant.headers("sales_executive"),
        )

        rows = (await db.execute(text("SELECT deal_id, lead_id, outcome FROM deal_outcomes"))).all()
        assert len(rows) == 2
        assert len({r[0] for r in rows}) == 2, "distinct deals"
        assert len({r[1] for r in rows}) == 1, "same lead"

    async def test_loss_reason_stored_as_enum_value(self, client, tenant, deal, db):
        client.patch(
            f"{V1}/deals/{deal['id']}/stage",
            json={"stage": "closed_lost", "loss_reason": "chose_competitor"},
            headers=tenant.headers("sales_executive"),
        )
        reason = (await db.execute(text("SELECT loss_reason FROM deal_outcomes"))).scalar()
        assert reason == "chose_competitor", "enums persist by value, matching the API contract"


class TestArchiving:
    def test_archived_deal_disappears(self, client, tenant, deal):
        client.delete(f"{V1}/deals/{deal['id']}", headers=tenant.headers("sales_manager"))
        assert client.get(f"{V1}/deals/{deal['id']}", headers=tenant.headers("sales_manager")).status_code == 404

    def test_archiving_a_lead_hides_its_deals(self, client, tenant, deal):
        """Otherwise an archived lead's deals linger in the pipeline board."""

        client.delete(f"/api/v1/leads/{tenant.lead_id}", headers=tenant.headers("sales_manager"))
        listing = client.get(f"{V1}/deals", headers=tenant.headers("sales_manager")).json()["data"]
        assert listing == []
