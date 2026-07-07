import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class LeadStatus(str, Enum):
    """Pipeline stage — drives the CRM Pipeline page and the Feedback
    Learning Agent's won/lost input (see DealOutcome in feedback.py).

    Named `status` (not `stage`) to match the frontend's types/index.ts
    `LeadStatus`, which committed to this name before the DB work. Kept a
    fixed enum rather than a per-tenant pipeline_stages table (Phase 4
    Module 4 decision) — lead-as-deal, no separate Deal entity."""

    NEW = "new"
    RESEARCHING = "researching"
    READY = "ready"
    CONTACTED = "contacted"
    DEMO_SCHEDULED = "demo_scheduled"
    PROPOSAL = "proposal"
    CLOSED_WON = "closed_won"
    CLOSED_LOST = "closed_lost"


class LeadPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Lead(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A prospect company being pursued by a tenant — distinct from
    `Company`, which is the tenant itself."""

    __tablename__ = "leads"

    name: Mapped[str] = mapped_column(String, index=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    website: Mapped[str | None] = mapped_column(String, nullable=True)
    country: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    employees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    annual_revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    """e.g. linkedin, csv_import, crm_sync, webform"""
    status: Mapped[LeadStatus] = mapped_column(default=LeadStatus.NEW, index=True)
    priority: Mapped[LeadPriority | None] = mapped_column(nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    external_crm_source: Mapped[str | None] = mapped_column(String, nullable=True)
    """e.g. salesforce, hubspot, zoho — which Integration this lead is mirrored from, if any"""
    external_crm_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    """The record id in the tenant's external CRM. The CRM is the source of
    truth for this lead's core identity fields; we own AI insights and push
    status/notes/meetings back (see Integration, IntegrationSyncLog)."""


class Contact(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """A lead company may have multiple people — kept separate from Lead.
    Carries its own company_id (not just lead_id) so no query can reach a
    contact without the tenant filter — the isolation rule is enforced
    directly, not via a join through Lead."""

    __tablename__ = "contacts"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    full_name: Mapped[str] = mapped_column(String)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    is_primary: Mapped[bool] = mapped_column(default=False)


class AIOutputMixin:
    """Shared shape for every AI-produced result. Never store just a number —
    model_name + model_version + confidence + explanation make results
    debuggable, auditable, and comparable across model changes. model_version
    resolves against ModelRegistryEntry. Applied to LeadScore, BuyingSignal,
    ICPScore, ResearchReport here; apply the same way to any future AI output
    table.
    """

    model_name: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)


class ResearchReport(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    """Structured output of the Research Agent — renders the Lead Details
    'AI Research' tab (profile, news, pain points). Distinct from
    AIInteractionLog, which stores the raw debug blob; this is the clean,
    queryable version. `sources` satisfies the research source-citation
    safety rule (a rep may repeat these claims to a prospect)."""

    __tablename__ = "ai_research_reports"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    generated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text)
    industry_insights: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_size_estimate: Mapped[str | None] = mapped_column(String, nullable=True)
    recent_news: Mapped[str | None] = mapped_column(Text, nullable=True)
    pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Citations backing the claims above — JSON list of URLs/references."""


class LeadScore(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    __tablename__ = "lead_scores"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    score: Mapped[int] = mapped_column(Integer)


class BuyingSignal(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    __tablename__ = "buying_signals"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    signal_type: Mapped[str] = mapped_column(String)
    """e.g. hiring, funding, expansion, product_launch, digital_transformation"""
    description: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ICPScore(Base, UUIDPrimaryKeyMixin, TenantMixin, AIOutputMixin, TimestampMixin):
    """Per-attribute fixed columns instead of a JSON blob — directly
    queryable/sortable and matches the explainability principle (a client
    renders each attribute score without parsing)."""

    __tablename__ = "icp_scores"

    lead_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), index=True)
    industry_score: Mapped[float] = mapped_column(Float)
    company_size_score: Mapped[float] = mapped_column(Float)
    region_score: Mapped[float] = mapped_column(Float)
    pain_point_score: Mapped[float] = mapped_column(Float)
    overall_score: Mapped[float] = mapped_column(Float)