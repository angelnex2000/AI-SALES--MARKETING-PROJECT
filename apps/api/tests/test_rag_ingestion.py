"""Knowledge ingestion and search, end to end through the API.

The gap this closes: `agents/rag/ingest.py` had been complete and tested since
Phase 8 Module 7, but `POST /rag/documents` created a `rag_index` job that no
worker consumed. Every uploaded document stayed in `uploaded`, so the Outreach
Agent had nothing to ground on — the RAG subsystem was finished except for the
one line that started it.
"""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.models.knowledge import DocumentStatus
from app.services import rag_service

V1 = "/api/v1"

CASE_STUDY = (
    "CityCare Hospitals reduced inbound support tickets by 38% within two quarters of "
    "rolling out automated triage. Average first-response time fell from 9 hours to 40 "
    "minutes across 12 clinics. The programme covered 240 staff and paid back in month "
    "five. Their operations director cited the reduction in after-hours escalations as "
    "the change clinicians noticed first."
)

VECTOR = [0.01] * 1536


class _Task:
    def __init__(self):
        self.calls: list[tuple] = []

    def delay(self, *args):
        self.calls.append(args)


@pytest.fixture
def fake_index_task(monkeypatch):
    task = _Task()
    monkeypatch.setattr("app.routers.rag.run_rag_index", task)
    return task


def upload(client, tenant, *, content=CASE_STUDY, role="marketing", title="CityCare case study"):
    return client.post(
        f"{V1}/rag/documents",
        json={"title": title, "document_category": "case_study", "content": content},
        headers=tenant.headers(role),
    )


class TestUpload:
    def test_upload_dispatches_indexing(self, client, tenant, fake_index_task):
        r = upload(client, tenant)
        assert r.status_code == 202, r.text
        assert fake_index_task.calls, "the job must reach a worker, not sit pending forever"
        job_id, document_id, company_id, content = fake_index_task.calls[0]
        assert content == CASE_STUDY
        assert company_id == str(tenant.company_id)

    def test_empty_content_is_rejected(self, client, tenant, fake_index_task):
        """Metadata alone indexes nothing, and a `ready` document over zero
        chunks shows the tenant a case study that can never ground a claim."""

        r = upload(client, tenant, content="   ")
        assert r.status_code == 422
        assert r.json()["error_code"] == "EMPTY_DOCUMENT"
        assert not fake_index_task.calls

    def test_oversized_content_is_rejected(self, client, tenant, fake_index_task):
        """The text travels to the worker as a Celery argument, so it travels
        through Redis — which is not a document store."""

        r = upload(client, tenant, content="x" * (rag_service.MAX_DOCUMENT_CHARS + 1))
        assert r.status_code == 422
        assert r.json()["error_code"] == "DOCUMENT_TOO_LARGE"

    def test_sales_executives_cannot_upload(self, client, tenant, fake_index_task):
        assert upload(client, tenant, role="sales_executive").status_code == 403

    def test_admin_can_upload(self, client, tenant, fake_index_task):
        assert upload(client, tenant, role="admin").status_code == 202


class TestIndexing:
    async def test_a_document_becomes_ready_with_chunks_and_embeddings(self, db, tenant):
        from app.models.knowledge import KnowledgeDocument

        doc = KnowledgeDocument(
            company_id=tenant.company_id,
            title="CityCare",
            document_category="case_study",
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()

        with patch(
            "agents.embeddings.model.embed",
            new=AsyncMock(side_effect=lambda texts: [VECTOR for _ in texts]),
        ):
            result = await rag_service.index_document(
                db, document_id=doc.id, company_id=tenant.company_id, content=CASE_STUDY
            )

        assert result["status"] == DocumentStatus.READY.value
        assert result["chunks"] >= 1
        chunks = (await db.execute(text("SELECT count(*) FROM knowledge_chunks"))).scalar()
        embeddings = (await db.execute(text("SELECT count(*) FROM knowledge_embeddings"))).scalar()
        assert chunks == embeddings == result["chunks"]

    async def test_an_embedding_failure_marks_the_document_failed_not_processing(self, db, tenant):
        """A document stuck in `processing` is excluded from search with
        nothing telling the tenant why."""

        from agents.embeddings.model import EmbeddingUnavailableError
        from app.models.knowledge import KnowledgeDocument

        doc = KnowledgeDocument(
            company_id=tenant.company_id,
            title="CityCare",
            document_category="case_study",
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()

        with patch(
            "agents.embeddings.model.embed",
            new=AsyncMock(side_effect=EmbeddingUnavailableError("no api key")),
        ):
            result = await rag_service.index_document(
                db, document_id=doc.id, company_id=tenant.company_id, content=CASE_STUDY
            )

        assert result["status"] == DocumentStatus.FAILED.value
        await db.refresh(doc)
        assert doc.status == DocumentStatus.FAILED

    async def test_indexing_another_tenants_document_is_refused(self, db, tenant, other_tenant):
        """A mis-routed job must not index one tenant's document under
        another's company_id."""

        from app.models.knowledge import KnowledgeDocument

        doc = KnowledgeDocument(
            company_id=other_tenant.company_id,
            title="Rival case study",
            document_category="case_study",
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()

        with pytest.raises(ValueError):
            await rag_service.index_document(
                db, document_id=doc.id, company_id=tenant.company_id, content=CASE_STUDY
            )

    async def test_the_embedding_model_is_recorded_per_row(self, db, tenant):
        """Vectors from different models are not comparable, so a later model
        change has to be detectable rather than silently degrading retrieval."""

        from app.models.knowledge import KnowledgeDocument

        doc = KnowledgeDocument(
            company_id=tenant.company_id,
            title="CityCare",
            document_category="case_study",
            status=DocumentStatus.UPLOADED,
        )
        db.add(doc)
        await db.commit()

        with patch(
            "agents.embeddings.model.embed",
            new=AsyncMock(side_effect=lambda texts: [VECTOR for _ in texts]),
        ):
            await rag_service.index_document(
                db, document_id=doc.id, company_id=tenant.company_id, content=CASE_STUDY
            )

        models = {
            row[0]
            for row in (
                await db.execute(text("SELECT DISTINCT embedding_model FROM knowledge_embeddings"))
            ).all()
        }
        assert models == {"text-embedding-3-small"}


class TestSearch:
    def test_search_distinguishes_no_matches_from_could_not_look(self, client, tenant):
        """Collapsing both into an empty list is how a grounded email silently
        becomes an ungrounded one."""

        with patch(
            "agents.rag.retriever.embedding_model.embed_one", new=AsyncMock(return_value=VECTOR)
        ):
            looked = client.post(
                f"{V1}/rag/search",
                json={"query": "support ticket reduction"},
                headers=tenant.headers("sales_executive"),
            ).json()["data"]
        assert looked["available"] is True
        assert looked["results"] == []
        assert looked["reason"]

    def test_an_unavailable_embedder_is_reported_as_such(self, client, tenant):
        from agents.embeddings.model import EmbeddingUnavailableError

        with patch(
            "agents.rag.retriever.embedding_model.embed_one",
            new=AsyncMock(side_effect=EmbeddingUnavailableError("no api key")),
        ):
            data = client.post(
                f"{V1}/rag/search",
                json={"query": "anything"},
                headers=tenant.headers("sales_executive"),
            ).json()["data"]
        assert data["available"] is False
        assert "api key" in data["reason"].lower()

    async def test_the_retrieval_is_logged_for_audit(self, client, db, tenant):
        """A claim in a sent email must be traceable to the chunks behind it."""

        with patch(
            "agents.rag.retriever.embedding_model.embed_one", new=AsyncMock(return_value=VECTOR)
        ):
            client.post(
                f"{V1}/rag/search",
                json={"query": "support ticket reduction"},
                headers=tenant.headers("sales_executive"),
            )
        logged = (await db.execute(text("SELECT query, used_for FROM rag_retrieval_logs"))).all()
        assert logged and logged[0][0] == "support ticket reduction"

    def test_search_reports_how_much_is_indexed(self, client, tenant):
        """"No results" over an empty knowledge base is a different message to
        the tenant than "no results" over 400 chunks."""

        with patch(
            "agents.rag.retriever.embedding_model.embed_one", new=AsyncMock(return_value=VECTOR)
        ):
            data = client.post(
                f"{V1}/rag/search", json={"query": "x"}, headers=tenant.headers("marketing")
            ).json()["data"]
        assert data["indexed_chunks"] == 0


class TestStats:
    def test_stats_report_document_status_and_stale_embeddings(self, client, tenant):
        data = client.get(f"{V1}/rag/stats", headers=tenant.headers("admin")).json()["data"]
        assert set(data["documents_by_status"]) >= {"uploaded", "ready", "failed"}
        assert data["stale_embedding_chunks"] == 0

    def test_stats_are_not_open_to_sales(self, client, tenant):
        assert (
            client.get(f"{V1}/rag/stats", headers=tenant.headers("sales_executive")).status_code
            == 403
        )

    async def test_stale_chunks_are_reported_after_a_model_change(self, db, tenant):
        """Reported, never re-embedded implicitly — re-embedding a corpus is a
        cost decision."""

        from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeEmbedding

        doc = KnowledgeDocument(
            company_id=tenant.company_id,
            title="Old",
            document_category="case_study",
            status=DocumentStatus.READY,
        )
        db.add(doc)
        await db.flush()
        chunk = KnowledgeChunk(
            company_id=tenant.company_id, document_id=doc.id, text="old text", chunk_index=0
        )
        db.add(chunk)
        await db.flush()
        db.add(
            KnowledgeEmbedding(
                company_id=tenant.company_id,
                chunk_id=chunk.id,
                embedding_model="all-MiniLM-L6-v2",
                embedding=[0.0] * 1536,
            )
        )
        await db.commit()

        stats = await rag_service.document_stats(db, company_id=tenant.company_id)
        assert stats["stale_embedding_chunks"] == 1


class TestTenantIsolation:
    """One tenant's case studies grounding another's outreach would leak
    commercial material between competitors — the worst failure this subsystem
    has."""

    def test_documents_are_listed_per_tenant(self, client, tenant, other_tenant, fake_index_task):
        upload(client, tenant, title="Ours")
        upload(client, other_tenant, title="Theirs")

        mine = client.get(f"{V1}/rag/documents", headers=tenant.headers("marketing")).json()["data"]
        assert [d["title"] for d in mine] == ["Ours"]

    def test_another_tenants_document_is_404(self, client, tenant, other_tenant, fake_index_task):
        doc_id = upload(client, other_tenant).json()["data"]["document_id"]
        r = client.get(f"{V1}/rag/documents/{doc_id}", headers=tenant.headers("marketing"))
        assert r.status_code == 404
        assert r.json()["error_code"] == "DOCUMENT_NOT_FOUND"
