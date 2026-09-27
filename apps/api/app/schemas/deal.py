import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.deal import DealStage

# Money is Decimal end to end — never float. Pydantic parses a JSON number or
# string into Decimal, and SQLAlchemy stores it in NUMERIC(14,2). See the note
# on Deal.amount for why float is unsafe for a column that gets summed into
# revenue forecasts.
Money = Decimal


class DealResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    name: str
    stage: DealStage
    amount: Money | None
    currency: str
    expected_close_date: datetime | None
    created_at: datetime


class DealCreate(BaseModel):
    lead_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    amount: Money | None = Field(default=None, ge=0, decimal_places=2, max_digits=14)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    expected_close_date: datetime | None = None

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        # ISO 4217 is uppercase; normalising here stops "usd" and "USD" being
        # treated as two currencies when the pipeline board groups totals.
        return v.upper()


class DealUpdate(BaseModel):
    """Dumped with exclude_unset, so an omitted field is left alone while an
    explicit null clears it.

    No `stage` field: moving a deal through the pipeline records outcomes and
    triggers a forecast, so it goes through PATCH /deals/{id}/stage instead of
    being a silent field edit here.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Money | None = Field(default=None, ge=0, decimal_places=2, max_digits=14)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    expected_close_date: datetime | None = None

    @field_validator("name", "currency")
    @classmethod
    def _not_cleared(cls, v, info):
        # Runs only when the field is actually sent. Both columns are NOT NULL.
        if v is None:
            raise ValueError(f"{info.field_name} cannot be null")
        return v.upper() if info.field_name == "currency" else v


class DealStageUpdate(BaseModel):
    stage: DealStage
    # Required by the service when moving to `closed_lost` — feedback learning
    # needs a structured enum reason, never free text.
    loss_reason: str | None = None


class PipelineColumn(BaseModel):
    stage: DealStage
    count: int
    totals_by_currency: dict[str, Money]
    """Per currency, deliberately not one summed number: adding a USD deal to
    an INR deal produces a figure that means nothing, and there is no FX source
    in this service."""
    deals: list[DealResponse]
