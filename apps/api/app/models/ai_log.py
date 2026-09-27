import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONColumn, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AgentTaskStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class AIInteractionLog(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One agent task: what it was given, what it returned, and whether it
    worked. Distinct from AIOutputMixin (LeadScore, BuyingSignal, ICPScore),
    which stores the structured *result*.

    **Phase 9 Module 3 made this record failures.** Until then it was written
    only after an agent returned, so a raising agent left nothing behind — the
    one table built for "auditing what an agent actually saw" was blind to
    precisely the case anyone would open it for. All that survived a failure
    was a string on the `Job` row, with no record of which step died, what it
    was handed, or how long it ran before dying.

    Written once, at the end of the attempt, rather than `running` first and
    updated after: a mid-workflow commit would persist a row belonging to a
    transaction that may still roll back. A hung agent is still diagnosable —
    it shows as a `running` Job with no task row for its step.
    """

    __tablename__ = "ai_interaction_logs"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    """Correlates every step of one workflow execution. Without it, "show me
    everything that happened in that run" is a guess based on timestamps, and
    two concurrent runs on the same lead are indistinguishable."""
    workflow: Mapped[str | None] = mapped_column(String, nullable=True)
    step: Mapped[str | None] = mapped_column(String, nullable=True)
    """The workflow step name, which is not always the agent name — `campaign`
    runs twice within one step, and a future workflow may reuse an agent."""
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=True, index=True
    )
    agent_name: Mapped[str] = mapped_column(String, index=True)
    model_version: Mapped[str] = mapped_column(String)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("leads.id"), nullable=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONColumn)
    output_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONColumn, nullable=True)
    """Nullable since Module 3: a failed attempt has no output, and storing
    `{}` would make "returned nothing" indistinguishable from "did not run"."""
    status: Mapped[AgentTaskStatus] = mapped_column(
        default=AgentTaskStatus.COMPLETED, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    """Which try this was. A task that succeeded on attempt 3 looks identical
    to one that succeeded first time unless this is recorded, and the
    difference is a provider degrading under load."""
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    """Stored rather than derived: `created_at` is set by the database clock
    and the timestamps by the application's, so subtracting them across a
    fleet compares two different clocks."""
