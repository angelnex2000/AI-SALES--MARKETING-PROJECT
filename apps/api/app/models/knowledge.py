import uuid
from enum import Enum

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

EMBEDDING_DIM = 1536
"""Matches OpenAI text-embedding-3-small. Revisit if the embedding model changes."""


class DocumentStatus(str, Enum):
    """Upload → extraction → chunking → embedding is async, like any other
    background job — status tracks where a document is in that pipeline."""

    UPLOADED = "uploaded"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class KnowledgeDocument(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A tenant's own product doc / case study / pricing sheet / playbook /
    past successful email — grounds AI-generated outreach so it never
    invents a claim the tenant hasn't actually made. Tenant-scoped like any
    other business data: Company A's case studies must never ground
    Company B's outreach."""

    __tablename__ = "knowledge_documents"

    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String)
    document_category: Mapped[str] = mapped_column(String)
    """case_study, product_doc, pricing, faq, playbook, past_email"""
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    file_type: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_url: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[DocumentStatus] = mapped_column(default=DocumentStatus.UPLOADED, index=True)


class KnowledgeChunk(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A retrievable slice of a KnowledgeDocument. The embedding lives in a
    separate KnowledgeEmbedding row (not a column here) so re-embedding with
    a new model doesn't require touching the chunk text, and so we can tell
    which chunks were embedded with an outdated model."""

    __tablename__ = "knowledge_chunks"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_documents.id"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    chunk_index: Mapped[int] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class KnowledgeEmbedding(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """The pgvector embedding for one chunk, tagged with the model that
    produced it. Stored on the existing Postgres instance via pgvector
    rather than a dedicated vector DB — per-tenant document volume doesn't
    justify the extra ops surface. Requires the `vector` Postgres extension
    (`CREATE EXTENSION IF NOT EXISTS vector;`)."""

    __tablename__ = "knowledge_embeddings"

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_chunks.id"), index=True
    )
    embedding_model: Mapped[str] = mapped_column(String)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))


class RAGRetrievalLog(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Records which chunks grounded a given AI generation — makes RAG's
    'grounded in approved knowledge' claim auditable. When an outreach email
    cites a case study, this is what traces the email back to the exact
    document. Distinct from AIInteractionLog's general raw input/output."""

    __tablename__ = "rag_retrieval_logs"

    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    query: Mapped[str] = mapped_column(Text)
    retrieved_chunk_ids: Mapped[str] = mapped_column(Text)
    """JSON list of KnowledgeChunk ids that were retrieved for this query."""
    used_for: Mapped[str] = mapped_column(String)
    """e.g. personalized_outreach, follow_up, objection_handling"""