import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.lead import LeadPriority, LeadStatus


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str | None
    website: str | None
    country: str | None
    city: str | None
    employees: int | None
    annual_revenue: float | None
    source: str | None
    status: LeadStatus
    priority: LeadPriority | None
    owner_id: uuid.UUID | None
    created_at: datetime


class LeadCreate(BaseModel):
    name: str
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    city: str | None = None
    employees: int | None = None
    source: str | None = None