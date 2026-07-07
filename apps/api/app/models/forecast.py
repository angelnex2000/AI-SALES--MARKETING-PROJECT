from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RevenueForecast(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Revenue Forecasting Agent output — company-scoped (a forecast is over
    the whole pipeline for a period), not lead-scoped. Append-only history so
    forecast accuracy can be evaluated after the period closes."""

    __tablename__ = "revenue_forecasts"

    forecast_period: Mapped[str] = mapped_column(String, index=True)
    """e.g. 2026-07 (month) or 2026-Q3 (quarter)"""
    predicted_revenue: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    model_name: Mapped[str] = mapped_column(String)
    model_version: Mapped[str] = mapped_column(String)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    """Snapshot of the pipeline inputs the forecast was computed from."""