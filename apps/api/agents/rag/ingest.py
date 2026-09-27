"""Document ingestion: text → chunks → embeddings → rows.

Runs on a worker, not in the request: a long document is hundreds of chunks
and hundreds of embeddings, and the upload endpoint returns 202 + a job id.

The status transitions on `KnowledgeDocument` are the contract with the UI —
`uploaded → processing → ready | failed`. **A document must never sit in
`processing` after a failure**: the RAG search silently excludes it, so a
tenant sees an uploaded case study that never grounds anything and has no
indication why.
"""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.embeddings import model as embedding_model
from agents.embeddings.model import EmbeddingUnavailableError
from agents.rag.chunker import chunk_text, estimate_tokens
from app.models.knowledge import (
    DocumentStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeEmbedding,
)

logger = logging.getLogger(__name__)


async def ingest_document(
    db: AsyncSession, *, document_id: uuid.UUID, company_id: uuid.UUID, text: str
) -> dict[str, Any]:
    """Chunk, embed and store one document. Returns a summary for the job."""

    document = await db.get(KnowledgeDocument, document_id)
    if document is None or document.company_id != company_id:
        # Tenant check even on an internal path: a mis-routed job must not
        # index one tenant's document under another's company_id.
        raise ValueError("document not found for this tenant")

    document.status = DocumentStatus.PROCESSING
    await db.commit()

    try:
        chunks = chunk_text(text)
        if not chunks:
            document.status = DocumentStatus.FAILED
            await db.commit()
            return {"chunks": 0, "status": document.status.value, "reason": "no extractable text"}

        vectors = await embedding_model.embed(chunks)
        identity = embedding_model.describe()

        for index, (body, vector) in enumerate(zip(chunks, vectors, strict=True)):
            chunk = KnowledgeChunk(
                company_id=company_id,
                document_id=document.id,
                text=body,
                chunk_index=index,
                token_count=estimate_tokens(body),
            )
            db.add(chunk)
            await db.flush()
            db.add(
                KnowledgeEmbedding(
                    company_id=company_id,
                    chunk_id=chunk.id,
                    # Recorded per row so a later model change is detectable
                    # rather than silently corrupting comparisons.
                    embedding_model=identity["embedding_model"],
                    embedding=vector,
                )
            )

        document.status = DocumentStatus.READY
        await db.commit()
        return {"chunks": len(chunks), "status": document.status.value, **identity}

    except EmbeddingUnavailableError as exc:
        # Explicitly `failed`, not left in `processing`: a document stuck
        # mid-pipeline is invisible to search with nothing explaining why.
        logger.error("embedding failed during ingestion", exc_info=exc)
        await db.rollback()
        document = await db.get(KnowledgeDocument, document_id)
        if document is not None:
            document.status = DocumentStatus.FAILED
            await db.commit()
        return {"chunks": 0, "status": DocumentStatus.FAILED.value, "reason": str(exc)}


async def reindex_stale(
    db: AsyncSession, *, company_id: uuid.UUID
) -> list[uuid.UUID]:
    """Chunk ids whose embedding came from a different model than the current one.

    Vectors from different models are not comparable, so mixing them degrades
    retrieval without erroring. This finds what needs re-embedding after a
    model change; it deliberately only reports, since re-embedding a corpus is
    a cost decision rather than something to trigger implicitly.
    """

    current = embedding_model.describe()["embedding_model"]
    stmt = select(KnowledgeEmbedding.chunk_id).where(
        KnowledgeEmbedding.company_id == company_id,
        KnowledgeEmbedding.embedding_model != current,
    )
    return list((await db.execute(stmt)).scalars().all())
