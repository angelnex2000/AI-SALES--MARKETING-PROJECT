import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    name: str = Field(min_length=1, max_length=255)
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    city: str | None = None
    employees: int | None = None
    annual_revenue: float | None = None
    source: str | None = None


class LeadUpdate(BaseModel):
    """Every field optional. The router dumps with exclude_unset, so an
    omitted field is left alone while an explicit null clears it.

    Deliberately no owner_id: reassignment is Gate 1 and goes through
    POST /leads/{id}/assign, which is Sales-Manager-only. Accepting it here
    would let a Sales Executive reassign leads with a plain PUT.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    city: str | None = None
    employees: int | None = None
    annual_revenue: float | None = None
    source: str | None = None
    status: LeadStatus | None = None
    priority: LeadPriority | None = None

    @field_validator("name")
    @classmethod
    def _name_not_cleared(cls, v: str | None) -> str | None:
        # Runs only when the caller actually sends `name`. Without this,
        # {"name": null} would set a NOT NULL column to null and surface as a
        # 500 at commit instead of a 422.
        if v is None:
            raise ValueError("name cannot be null")
        return v


class AssignRequest(BaseModel):
    owner_user_id: uuid.UUID