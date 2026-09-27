"""Module 9 — RAG (retrieval only).

RAG is scoped to grounding Personalized Outreach — there is deliberately NO
`/rag/generate` here (that lives behind `/outreach/generate`). Tenant isolation
is the top risk: one tenant's documents must never ground another's outreach,
so every read filters company_id.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.job import Job, JobStatus
from app.models.knowledge import DocumentStatus, KnowledgeDocument, RAGRetrievalLog
from app.models.user import Role, User
from app.schemas.common import ok
from app.services import job_service, rag_service
from app.tasks import run_rag_index

router = APIRouter()


class DocumentCreate(BaseModel):
    title: str
    document_category: str
    content: str
    """The document text to index. Metadata alone indexes nothing — a document
    row with no content produced a `ready` status over zero chunks, so the
    Campaign Studio showed an uploaded case study that could never ground a
    claim. Kept as text rather than a file upload because there is no object
    storage yet; see `rag_service.MAX_DOCUMENT_CHARS` for the size bound."""
    file_name: str | None = None
    file_type: str | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_category: str
    status: DocumentStatus


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    lead_id: uuid.UUID | None = None
    """Recorded on the retrieval log so a claim in a sent email is traceable to
    the chunks that grounded it."""


@router.post("/documents", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    payload: DocumentCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING, Role.ADMIN)),
):
    """Create the document row and queue chunk → embed → store on a worker.

    Until Phase 9 this created a `rag_index` Job that nothing dispatched, so
    every document stayed in `uploaded` and the Outreach Agent had nothing to
    ground on — the RAG subsystem was complete and tested end to end except for
    the one line that started it.
    """

    content = rag_service.validate_content(payload.content)
    fields = payload.model_dump(exclude_none=True, exclude={"content"})

    doc = KnowledgeDocument(
        company_id=user.company_id,
        uploaded_by_user_id=user.id,
        status=DocumentStatus.UPLOADED,
        **fields,
    )
    db.add(doc)
    await db.flush()
    job = Job(
        company_id=user.company_id,
        job_type="rag_index",
        created_by_user_id=user.id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(doc)

    await job_service.enqueue(
        db,
        job=job,
        task=run_rag_index,
        args=(str(job.id), str(doc.id), str(user.company_id), content),
    )
    return ok(data={"document_id": doc.id, "status": doc.status, "job_id": job.id}, message="Indexing started")


@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.company_id == user.company_id)
    )
    return ok(data=[DocumentResponse.model_validate(d) for d in rows.scalars().all()])


@router.get("/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    doc = await db.get(KnowledgeDocument, document_id)
    if doc is None or doc.company_id != user.company_id:
        raise NotFoundError("Document not found", error_code="DOCUMENT_NOT_FOUND")
    return ok(data=DocumentResponse.model_validate(doc))


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    doc = await db.get(KnowledgeDocument, document_id)
    if doc is None or doc.company_id != user.company_id:
        raise NotFoundError("Document not found", error_code="DOCUMENT_NOT_FOUND")
    await db.delete(doc)
    await db.commit()
    return ok(message="Document deleted")


@router.post("/search")
async def search(
    payload: SearchRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """Semantic search over this tenant's READY chunks.

    An empty result is a valid 200, never an error — but the response carries
    `available` and `reason`, so "you have not uploaded anything" is
    distinguishable from "the embedding provider is unreachable". Collapsing
    those two into an empty list is how a grounded email silently becomes an
    ungrounded one.

    Note the pgvector similarity query itself remains a TODO in
    `agents/rag/retriever.py` (SQLite has no `<=>` operator, so it needs a
    `@pytest.mark.postgres` test) — this endpoint is wired to the real
    retriever and returns its honest answer rather than a hardcoded `[]`.
    """

    return ok(
        data=await rag_service.search(
            db, user=user, query=payload.query, top_k=payload.top_k, lead_id=payload.lead_id
        )
    )


@router.get("/stats")
async def knowledge_stats(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.MARKETING)),
):
    """Document counts by status, plus chunks embedded with a superseded model.

    Stale chunks are reported, never re-embedded implicitly: vectors from
    different models are not comparable, so a model change degrades retrieval
    silently — but re-embedding a corpus is a cost decision.
    """

    return ok(data=await rag_service.document_stats(db, company_id=user.company_id))


@router.get("/retrievals/{retrieval_id}")
async def get_retrieval(
    retrieval_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    log = await db.get(RAGRetrievalLog, retrieval_id)
    if log is None or log.company_id != user.company_id:
        raise NotFoundError("Retrieval not found", error_code="RETRIEVAL_NOT_FOUND")
    return ok(
        data={
            "id": log.id,
            "query": log.query,
            "retrieved_chunk_ids": log.retrieved_chunk_ids,
            "used_for": log.used_for,
            "created_at": log.created_at,
        }
    )
