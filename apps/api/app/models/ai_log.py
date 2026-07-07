import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AIInteractionLog(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Raw input/output capture per agent call — distinct from
    AIOutputMixin (LeadScore, BuyingSignal, ICPScore), which stores the
    structured *result*. This is for debugging hallucinations and auditing
    what an agent was actually given and actually returned."""

    __tablename__ = "ai_interaction_logs"

    agent_name: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str] = mapped_column(String)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    output_payload: Mapped[dict[str, Any]] = mapped_column(JSONB)