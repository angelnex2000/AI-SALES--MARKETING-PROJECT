"""Tenant isolation and assigned-only visibility.

The hardest requirement in the product: one tenant must never see another's
data, and a Sales Executive must only see leads assigned to them. Both are
enforced in SQL, so these tests hit the real database rather than mocking.

Cross-tenant access must return **404, never 403** — a 403 confirms the
resource exists, which is itself a leak.
"""

import pytest

V1 = "/api/v1"


@pytest.fixture
async def cross(client, tenant, other_tenant):
    """Both tenants seeded; returns them for readability in each test."""

    return tenant, other_tenant


class TestCrossTenantReads:
    def test_cannot_read_another_tenants_lead(self, client, cross):
        mine, theirs = cross
        r = client.get(f"{V1}/leads/{theirs.lead_id}", headers=mine.headers("sales_manager"))
        assert r.status_code == 404
        assert r.status_code != 403, "403 would confirm the lead exists"

    def test_cannot_list_another_tenants_lead_contacts(self, client, cross):
        mine, theirs = cross
        r = client.get(
            f"{V1}/leads/{theirs.lead_id}/contacts", headers=mine.headers("sales_manager")
        )
        assert r.status_code == 404

    def test_lead_list_contains_only_own_tenant(self, client, cross):
        mine, theirs = cross
        r = client.get(f"{V1}/leads/", headers=mine.headers("sales_manager"))
        assert r.status_code == 200
        ids = {row["id"] for row in r.json()["data"]}
        assert str(theirs.lead_id) not in ids
        assert str(mine.lead_id) in ids


class TestCrossTenantWrites:
    def test_cannot_update_another_tenants_lead(self, client, cross):
        mine, theirs = cross
        r = client.put(
            f"{V1}/leads/{theirs.lead_id}",
            json={"name": "Hijacked"},
            headers=mine.headers("sales_manager"),
        )
        assert r.status_code == 404

    def test_cannot_archive_another_tenants_lead(self, client, cross):
        mine, theirs = cross
        r = client.delete(f"{V1}/leads/{theirs.lead_id}", headers=mine.headers("sales_manager"))
        assert r.status_code == 404

    def test_cannot_create_a_deal_on_another_tenants_lead(self, client, cross):
        mine, theirs = cross
        r = client.post(
            f"{V1}/deals",
            json={"lead_id": str(theirs.lead_id), "name": "Sneaky", "amount": "1.00"},
            headers=mine.headers("sales_manager"),
        )
        assert r.status_code == 404

    def test_cannot_assign_a_lead_to_another_tenants_user(self, client, cross):
        """The assignee check is what stops a lead being handed across tenants —
        db.get() by primary key carries no tenant filter of its own."""

        mine, theirs = cross
        r = client.post(
            f"{V1}/leads/{mine.lead_id}/assign",
            json={"owner_user_id": str(theirs.exec_id)},
            headers=mine.headers("sales_manager"),
        )
        assert r.status_code == 404
        assert r.json()["error_code"] == "USER_NOT_FOUND"


class TestAssignedOnly:
    """A Sales Executive sees only their own leads — same tenant, different rep."""

    def test_exec_sees_only_assigned_leads(self, client, tenant):
        r = client.get(f"{V1}/leads/", headers=tenant.headers("sales_executive"))
        assert [row["id"] for row in r.json()["data"]] == [str(tenant.lead_id)]

    def test_other_exec_sees_nothing(self, client, tenant):
        r = client.get(f"{V1}/leads/", headers=tenant.headers("sales_executive_2"))
        assert r.json()["data"] == []

    def test_unassigned_lead_is_404_for_the_other_exec(self, client, tenant):
        r = client.get(f"{V1}/leads/{tenant.lead_id}", headers=tenant.headers("sales_executive_2"))
        assert r.status_code == 404

    def test_manager_sees_every_lead_in_the_tenant(self, client, tenant):
        r = client.get(f"{V1}/leads/", headers=tenant.headers("sales_manager"))
        assert str(tenant.lead_id) in {row["id"] for row in r.json()["data"]}

    def test_exec_created_lead_is_self_owned(self, client, tenant):
        """Otherwise a rep creates a lead and immediately loses sight of it."""

        r = client.post(
            f"{V1}/leads/", json={"name": "Self serve"}, headers=tenant.headers("sales_executive")
        )
        assert r.status_code == 201, r.text
        assert r.json()["data"]["owner_id"] == str(tenant.exec_id)


class TestJobIsolation:
    def test_job_list_is_tenant_scoped(self, client, cross):
        mine, _ = cross
        r = client.get(f"{V1}/ai/jobs", headers=mine.headers("sales_manager"))
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_cannot_list_jobs_for_another_tenants_lead(self, client, cross):
        mine, theirs = cross
        r = client.get(
            f"{V1}/ai/jobs?lead_id={theirs.lead_id}", headers=mine.headers("sales_manager")
        )
        assert r.status_code == 404
