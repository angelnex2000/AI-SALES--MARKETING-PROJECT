import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ContactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    full_name: str
    email: EmailStr | None
    phone: str | None
    job_title: str | None
    department: str | None
    is_primary: bool


class ContactCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    job_title: str | None = None
    department: str | None = None
    is_primary: bool = False


class ContactUpdate(BaseModel):
    """Dumped with exclude_unset, so an omitted field is left alone while an
    explicit null clears it."""

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = None
    job_title: str | None = None
    department: str | None = None
    is_primary: bool | None = None

    @field_validator("full_name", "is_primary")
    @classmethod
    def _not_cleared(cls, v, info):
        # Only runs when the caller actually sends the field. Both columns are
        # NOT NULL, so an explicit null must be a 422 rather than a 500 at commit.
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v


class ActivityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    deal_id: uuid.UUID | None
    actor_id: uuid.UUID
    activity_type: str
    description: str
    created_at: datetime


class ActivityCreate(BaseModel):
    activity_type: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1)
    deal_id: uuid.UUID | None = None
    """Optional — which opportunity this was about. Validated against the
    lead, so it must be a deal on the same lead."""


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    deal_id: uuid.UUID | None
    author_id: uuid.UUID
    body: str
    created_at: datetime
    updated_at: datetime


class NoteCreate(BaseModel):
    body: str = Field(min_length=1)
    deal_id: uuid.UUID | None = None


class NoteUpdate(BaseModel):
    """Only the body is editable. `deal_id` is fixed at creation and the
    author never changes — a note keeps showing who wrote it."""

    body: str = Field(min_length=1)


class TimelineEvent(BaseModel):
    """Computed, not a table — merges activities, AI outputs, emails, meetings,
    and deal stage changes into one chronological view for the Lead Details
    Timeline tab."""

    type: str
    timestamp: datetime
    summary: str | None = None
