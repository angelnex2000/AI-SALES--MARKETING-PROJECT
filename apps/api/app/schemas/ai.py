import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from agents.reply_intent.labels import ReplyIntent
from app.models.ai_log import AgentTaskStatus
from app.models.job import JobStatus
from app.models.model_registry import ModelStatus


class _FromAttrs(BaseModel):
    # protected_namespaces=() silences pydantic's "model_" warning. Every AI
    # output schema here carries model_name/model_version by design
    # (AIOutputMixin), so the collision with pydantic's reserved prefix is
    # permanent — better to disable the check once than rename the contract.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class JobResponse(_FromAttrs):
    id: uuid.UUID
    job_type: str
    lead_id: uuid.UUID | None
    status: JobStatus
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class ResearchReportResponse(_FromAttrs):
    id: uuid.UUID
    lead_id: uuid.UUID
    summary: str
    industry_insights: str | None
    company_size_estimate: str | None
    recent_news: str | None
    pain_points: str | None
    sources: str | None
    model_name: str
    model_version: str
    confidence: float
    explanation: str
    created_at: datetime


class LeadScoreResponse(_FromAttrs):
    id: uuid.UUID
    lead_id: uuid.UUID
    score: int
    model_name: str
    model_version: str
    confidence: float
    explanation: str
    created_at: datetime


class BuyingSignalResponse(_FromAttrs):
    id: uuid.UUID
    lead_id: uuid.UUID
    signal_type: str
    description: str
    source_url: str | None
    detected_at: datetime
    model_name: str
    model_version: str
    confidence: float
    explanation: str


class ICPScoreResponse(_FromAttrs):
    id: uuid.UUID
    lead_id: uuid.UUID
    industry_score: float
    company_size_score: float
    region_score: float
    pain_point_score: float
    overall_score: float
    model_name: str
    model_version: str
    confidence: float
    explanation: str


class ReplyIntentResponse(_FromAttrs):
    id: uuid.UUID
    reply_id: uuid.UUID
    lead_id: uuid.UUID
    intent: ReplyIntent
    confidence: float
    suggested_action: str | None
    matched_phrase: str | None
    """The words the label was read from — the Outreach Center shows this
    under the suggested action, so a rep can disagree with the reading before
    acting on it rather than after."""
    alternative_intents: list[dict[str, Any]] | None
    model_name: str
    model_version: str
    explanation: str
    created_at: datetime


class RevenueForecastResponse(_FromAttrs):
    id: uuid.UUID
    forecast_period: str
    currency: str
    predicted_revenue: Decimal
    """`Decimal`, not float, end to end — this is money summed across a whole
    pipeline, and serialising through float would reintroduce the error
    `Deal.amount` is NUMERIC to avoid."""
    committed_revenue: Decimal
    weighted_pipeline: Decimal
    confidence: float
    model_name: str
    model_version: str
    explanation: str
    breakdown: dict[str, Any] | None
    input_summary: str | None
    created_at: datetime


class ModelRegistryResponse(_FromAttrs):
    id: uuid.UUID
    model_name: str
    model_version: str
    file_path: str
    metrics: dict[str, Any] | None
    status: ModelStatus


class AIInteractionLogResponse(_FromAttrs):
    """One agent task. Carries the full section-8 contract since Module 3 —
    including `status`/`error`, so a failed attempt is a row rather than a
    silence."""

    id: uuid.UUID
    run_id: uuid.UUID | None
    workflow: str | None
    step: str | None
    job_id: uuid.UUID | None
    agent_name: str
    model_version: str
    lead_id: uuid.UUID | None
    input_payload: dict[str, Any]
    output_payload: dict[str, Any] | None
    status: AgentTaskStatus
    error: str | None
    attempt: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    created_at: datetime
