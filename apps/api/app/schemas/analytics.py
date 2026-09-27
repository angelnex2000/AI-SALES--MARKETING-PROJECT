"""Analytics response shapes.

Money is `Decimal` and always keyed by currency — there is deliberately no
single `pipeline_value` scalar, because adding a USD deal to an INR deal
produces a figure that means nothing and this service has no FX rates.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.deal import DealStage


class DashboardMetrics(BaseModel):
    total_leads: int
    high_priority_leads: int
    unassigned_leads: int
    open_deals: int
    won_deals: int
    lost_deals: int
    pipeline_value_by_currency: dict[str, Decimal]
    won_value_by_currency: dict[str, Decimal]
    meetings_scheduled: int
    ai_jobs_completed: int
    ai_jobs_failed: int
    ai_jobs_in_flight: int
    generated_at: datetime
    """Stamped server-side so a cached dashboard can show how stale it is."""


class RevenueSummary(BaseModel):
    closed_won_by_currency: dict[str, Decimal]
    open_pipeline_by_currency: dict[str, Decimal]


class TeamMemberPerformance(BaseModel):
    user_id: str
    full_name: str
    role: str
    total_leads: int
    active_leads: int


class FunnelStage(BaseModel):
    stage: DealStage
    count: int
