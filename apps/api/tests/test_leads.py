"""Leads and contacts: CRUD, Gate 1 assignment, soft delete."""

from sqlalchemy import text

V1 = "/api/v1/leads"


class TestUpdateSemantics:
    """Payloads are dumped with exclude_unset, so an omitted field is left
    alone while an explicit null clears it. `exclude_none` used to drop both,
    making a nullable field impossible to clear."""

    def test_omitted_fields_are_left_alone(self, client, tenant):
        client.put(f"{V1}/{tenant.lead_id}", json={"industry": "SaaS"}, headers=tenant.headers("sales_manager"))
        r = client.put(f"{V1}/{tenant.lead_id}", json={"city": "Berlin"}, headers=tenant.headers("sales_manager"))
        assert r.json()["data"]["industry"] == "SaaS"
        assert r.json()["data"]["city"] == "Berlin"

    def test_explicit_null_clears_a_nullable_field(self, client, tenant):
        client.put(f"{V1}/{tenant.lead_id}", json={"industry": "SaaS"}, headers=tenant.headers("sales_manager"))
        r = client.put(f"{V1}/{tenant.lead_id}", json={"industry": None}, headers=tenant.headers("sales_manager"))
        assert r.json()["data"]["industry"] is None

    def test_null_on_a_not_null_column_is_422_not_500(self, client, tenant):
        r = client.put(f"{V1}/{tenant.lead_id}", json={"name": None}, headers=tenant.headers("sales_manager"))
        assert r.status_code == 422


class TestGate1Assignment:
    """Only a Sales Manager assigns, and only to a Sales Executive in the same
    company. Reassignment must not be possible through the plain PUT."""

    def test_exec_cannot_assign(self, client, tenant):
        r = client.post(
            f"{V1}/{tenant.lead_id}/assign",
            json={"owner_user_id": str(tenant.exec2_id)},
            headers=tenant.headers("sales_executive"),
        )
        assert r.status_code == 403

    def test_cannot_assign_to_a_non_executive(self, client, tenant):
        r = client.post(
            f"{V1}/{tenant.lead_id}/assign",
            json={"owner_user_id": str(tenant.manager_id)},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 403

    def test_manager_assigns_to_an_executive(self, client, tenant):
        r = client.post(
            f"{V1}/{tenant.lead_id}/assign",
            json={"owner_user_id": str(tenant.exec2_id)},
            headers=tenant.headers("sales_manager"),
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["owner_id"] == str(tenant.exec2_id)

    def test_owner_cannot_be_changed_via_plain_update(self, client, tenant):
        """LeadUpdate deliberately has no owner_id — accepting one would let a
        Sales Executive reassign leads to themselves and bypass Gate 1."""

        client.put(
            f"{V1}/{tenant.lead_id}",
            json={"owner_id": str(tenant.exec2_id)},
            headers=tenant.headers("sales_executive"),
        )
        r = client.get(f"{V1}/{tenant.lead_id}", headers=tenant.headers("sales_manager"))
        assert r.json()["data"]["owner_id"] == str(tenant.exec_id), "owner must be unchanged"


class TestSoftDelete:
    """17 tables reference leads.id with no ON DELETE rule, so a hard delete
    raises a ForeignKeyViolation as soon as a lead has any child data — and
    cascading would destroy append-only AI history."""

    def test_exec_cannot_archive(self, client, tenant):
        r = client.delete(f"{V1}/{tenant.lead_id}", headers=tenant.headers("sales_executive"))
        assert r.status_code == 403

    def test_archived_lead_disappears_from_the_api(self, client, tenant):
        client.delete(f"{V1}/{tenant.lead_id}", headers=tenant.headers("sales_manager"))
        assert client.get(f"{V1}/{tenant.lead_id}", headers=tenant.headers("sales_manager")).status_code == 404
        listing = client.get(f"{V1}/", headers=tenant.headers("sales_manager")).json()["data"]
        assert str(tenant.lead_id) not in {row["id"] for row in listing}

    async def test_archived_row_survives_in_the_database(self, client, tenant, db):
        client.delete(f"{V1}/{tenant.lead_id}", headers=tenant.headers("sales_manager"))
        total = (await db.execute(text("SELECT count(*) FROM leads"))).scalar()
        archived = (
            await db.execute(text("SELECT count(*) FROM leads WHERE archived_at IS NOT NULL"))
        ).scalar()
        assert total == 1 and archived == 1, "the row must remain so AI history stays valid"


class TestContacts:
    def test_only_one_primary_contact_per_lead(self, client, tenant):
        for name in ("First", "Second"):
            client.post(
                f"{V1}/{tenant.lead_id}/contacts",
                json={"full_name": name, "is_primary": True},
                headers=tenant.headers("sales_executive"),
            )
        rows = client.get(
            f"{V1}/{tenant.lead_id}/contacts", headers=tenant.headers("sales_executive")
        ).json()["data"]
        assert sum(1 for c in rows if c["is_primary"]) == 1

    def test_contact_update_clears_a_field_with_null(self, client, tenant):
        cid = tenant.contact_id
        client.put(f"{V1}/contacts/{cid}", json={"phone": "+91 555"}, headers=tenant.headers("sales_executive"))
        r = client.put(f"{V1}/contacts/{cid}", json={"phone": None}, headers=tenant.headers("sales_executive"))
        assert r.json()["data"]["phone"] is None

    def test_archived_contact_is_gone_but_row_remains(self, client, tenant):
        """email_drafts.contact_id references this row; a hard delete would
        break a pending Gate 2 draft."""

        client.delete(f"{V1}/contacts/{tenant.contact_id}", headers=tenant.headers("sales_executive"))
        rows = client.get(
            f"{V1}/{tenant.lead_id}/contacts", headers=tenant.headers("sales_executive")
        ).json()["data"]
        assert str(tenant.contact_id) not in {c["id"] for c in rows}

    def test_unassigned_exec_cannot_reach_contacts(self, client, tenant):
        r = client.get(
            f"{V1}/{tenant.lead_id}/contacts", headers=tenant.headers("sales_executive_2")
        )
        assert r.status_code == 404
