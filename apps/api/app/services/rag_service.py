"""Knowledge-base ingestion and retrieval.

`agents/rag/ingest.py` has been complete and tested since Phase 8 Module 7, but
nothing reached it: `POST /rag/documents` created a `rag_index` Job that no
worker consumed, so every uploaded document sat in `uploaded` forever and the
Outreach Agent had nothing to ground on. This module is the missing wiring.

Two rules carried over from the agent layer, enforced here because this is the
layer that touches the database:

**Never cross tenants.** Ingestion and search both filter `company_id`. One
tenant's case studies grounding another's outreach would leak commercial
material between competitors — the single worst failure this subsystem has.

**"Could not look" is not "found nothing".** The retriever distinguishes them
(`available=False` vs an empty `chunks` list) and `search` passes that
distinction through rather than flattening both to "no results", because one
means the tenant should upload something and the other means an operator should
check the embedding provider.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.rag import ingest
from agents.rag.retriever import RAGRetriever
from app.core.exceptions import NotFoundError, ValidationError
from app.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    RAGRetrievalLog,
)
from app.models.user import User

# Document text travels to the worker as a Celery argument, so it travels
# through the broker. Capped rather than unbounded: a 50MB paste would be a
# 50MB Redis message, and Redis is not a document store.
MAX_DOCUMENT_CHARS = 200_000


async def require_document(
    db: AsyncSession, *, document_id: uuid.UUID, company_id: uuid.UUID
) -> KnowledgeDocument:
    """404 for another tenant's document — never 403, which would confirm it
    exists."""

    document = await db.get(KnowledgeDocument, document_id)
    if document is None or document.company_id != company_id:
        raise NotFoundError("Document not found", error_code="DOCUMENT_NOT_FOUND")
    return document


def validate_content(content: str) -> str:
    text = (content or "").strip()
    if not text:
        raise ValidationError(
            "Document content is empty — there is nothing to index",
            error_code="EMPTY_DOCUMENT",
        )
    if len(text) > MAX_DOCUMENT_CHARS:
        raise ValidationError(
            f"Document is {len(text)} characters; the limit is {MAX_DOCUMENT_CHARS}",
            error_code="DOCUMENT_TOO_LARGE",
        )
    return text


async def index_document(
    db: AsyncSession, *, document_id: uuid.UUID, company_id: uuid.UUID, content: str
) -> dict[str, Any]:
    """Run ingestion for one document. Called from the worker.

    Delegates to `agents.rag.ingest`, which owns the status transitions —
    including setting `FAILED` explicitly rather than leaving a document in
    `processing`, where RAG search excludes it with nothing telling the tenant
    why.
    """

    return await ingest.ingest_document(
        db, document_id=document_id, company_id=company_id, text=content
    )


async def search(
    db: AsyncSession, *, user: User, query: str, top_k: int = 5, lead_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Semantic search over this tenant's READY chunks.

    An empty result is a valid 200, not an error — but it is reported with the
    reason, so "you have not uploaded anything" reads differently from "the
    embedding provider is down".
    """

    ready_chunks = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeChunk)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .where(
                KnowledgeChunk.company_id == user.company_id,
                KnowledgeDocument.status == DocumentStatus.READY,
            )
        )
    ).scalar() or 0

    result = await RAGRetriever().run(
        {"query": query, "company_id": str(user.company_id), "top_k": top_k}
    )

    # Logged for audit: a claim in a sent email must be traceable to the chunks
    # that grounded it, which means recording the retrieval that produced them.
    db.add(
        RAGRetrievalLog(
            company_id=user.company_id,
            lead_id=lead_id,
            user_id=user.id,
            query=query,
            retrieved_chunk_ids=",".join(str(c.get("id", "")) for c in result.get("chunks", [])),
            used_for="search",
        )
    )
    await db.commit()

    return {
        "query": query,
        "results": result.get("chunks", []),
        "grounded": result.get("grounded", False),
        # False means we could not look at all; the caller must not read that
        # as "this tenant has no relevant material".
        "available": result.get("available", True),
        "reason": result.get("reason"),
        "indexed_chunks": ready_chunks,
        "relevance_threshold": result.get("relevance_threshold"),
    }


async def document_stats(db: AsyncSession, *, company_id: uuid.UUID) -> dict[str, Any]:
    """Per-status document counts plus stale-embedding chunks.

    `reindex_stale` reports rather than acts: vectors from different models are
    not comparable, so a model change silently degrades retrieval, but
    re-embedding a corpus is a cost decision rather than something to trigger
    implicitly.
    """

    rows = (
        await db.execute(
            select(KnowledgeDocument.status, func.count())
            .where(KnowledgeDocument.company_id == company_id)
            .group_by(KnowledgeDocument.status)
        )
    ).all()
    counts = {status.value: 0 for status in DocumentStatus}
    for status, total in rows:
        counts[getattr(status, "value", str(status))] = total

    stale = await ingest.reindex_stale(db, company_id=company_id)
    return {"documents_by_status": counts, "stale_embedding_chunks": len(stale)}


__all__ = [
    "MAX_DOCUMENT_CHARS",
    "document_stats",
    "index_document",
    "require_document",
    "search",
    "validate_content",
]
