from enum import Enum
from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ModelStatus(str, Enum):
    TRAINING = "training"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ModelRegistryEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Tracks trained model artifacts so we know which model_version is
    currently serving production traffic.

    Deliberately NOT tenant-scoped (no TenantMixin): the default here is
    one shared model per model_name, trained on aggregated data across all
    tenants, not a model per customer. This is a default, not a settled
    decision — revisit if per-tenant model training is ever required; it
    would need TenantMixin added and a very different training pipeline.
    """

    __tablename__ = "model_registry_entries"

    model_name: Mapped[str] = mapped_column(String, index=True)
    """e.g. lead_scoring, reply_intent, revenue_forecasting, embeddings"""
    model_version: Mapped[str] = mapped_column(String, unique=True, index=True)
    file_path: Mapped[str] = mapped_column(String)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ModelStatus] = mapped_column(default=ModelStatus.TRAINING, index=True)