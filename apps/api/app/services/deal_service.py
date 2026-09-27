"""Deal business logic and the CRM pipeline.

A Deal is a qualified revenue opportunity against a Lead (1 Lead : N Deal).
A deal has no owner column of its own — ownership derives from the parent
lead, so there is exactly one assignment gate (Gate 1) and isolation is
always checked through `lead_service`.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.feedback_learning.loss_reasons import LossReason
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.deal import Deal, DealStage
from app.models.feedback import DealOutcome, Outcome
from app.models.job import Job, JobStatus
from app.models.lead import Lead
from app.models.user import Role, User


def _visible(stmt: Select, *, user: User) -> Select:
    """Tenant scope + assigned-only + archived filtering, in one place.

    Joins Lead because a Sales Executive's visibility is defined by lead
    ownership, and because a deal belonging to an archived lead must
    disappear along with its lead.
    """

    stmt = stmt.join(Lead, Deal.lead_id == Lead.id).where(
        Deal.company_id == user.company_id,
        Deal.archived_at.is_(None),
        Lead.archived_at.is_(None),
    )
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == user.id)
    return stmt


async def list_deals(
    db: AsyncSession,
    *,
    user: User,
    stage: DealStage | None = None,
    lead_id: uuid.UUID | None = None,
) -> list[Deal]:
    stmt = _visible(select(Deal), user=user)
    if stage is not None:
        stmt = stmt.where(Deal.stage == stage)
    if lead_id is not None:
        stmt = stmt.where(Deal.lead_id == lead_id)
    return list((await db.execute(stmt)).scalars().all())


async def require_deal(db: AsyncSession, *, deal_id: uuid.UUID, user: User) -> Deal:
    stmt = _visible(select(Deal).where(Deal.id == deal_id), user=user)
    deal = (await db.execute(stmt)).scalar_one_or_none()
    if deal is None:
        raise NotFoundError("Deal not found", error_code="DEAL_NOT_FOUND")
    return deal


async def create_deal(db: AsyncSession, *, data: dict, user: User) -> Deal:
    from app.services import lead_service

    # The parent lead must be visible to the caller (tenant + assignment).
    await lead_service.require_lead(
        db, lead_id=data["lead_id"], company_id=user.company_id, current_user=user
    )
    deal = Deal(company_id=user.company_id, **data)
    db.add(deal)
    await db.commit()
    await db.refresh(deal)
    return deal


async def update_deal(db: AsyncSession, *, deal_id: uuid.UUID, changes: dict, user: User) -> Deal:
    deal = await require_deal(db, deal_id=deal_id, user=user)
    for field, value in changes.items():
        setattr(deal, field, value)
    await db.commit()
    await db.refresh(deal)
    return deal


async def archive_deal(db: AsyncSession, *, deal_id: uuid.UUID, user: User) -> None:
    deal = await require_deal(db, deal_id=deal_id, user=user)
    deal.archived_at = datetime.now(UTC)
    await db.commit()


def _enqueue_forecast(db: AsyncSession, *, user: User, lead_id: uuid.UUID) -> None:
    """Deal stage changes shift the pipeline — recompute the forecast async
    (forecasting is a slow ML agent, never inline)."""

    db.add(
        Job(
            company_id=user.company_id,
            job_type="revenue_forecast",
            lead_id=lead_id,
            status=JobStatus.PENDING,
        )
    )


async def change_stage(
    db: AsyncSession, *, deal_id: uuid.UUID, stage: DealStage, loss_reason: str | None, user: User
) -> Deal:
    """A business event, not a field edit: guards reopening, records the
    won/lost outcome that feedback learning trains on, and refreshes the
    forecast."""

    deal = await require_deal(db, deal_id=deal_id, user=user)

    # Reopening a closed-won deal rewrites recognised revenue — manager only.
    if deal.stage == DealStage.CLOSED_WON and stage != DealStage.CLOSED_WON:
        if user.role != Role.SALES_MANAGER:
            raise ForbiddenError("Only a Sales Manager can reopen a closed-won deal")

    if stage in (DealStage.CLOSED_LOST, DealStage.CLOSED_WON):
        # Re-closing an already-closed deal would write a second outcome row and
        # double-count the deal in retraining.
        if deal.stage == stage:
            raise ValidationError(
                f"Deal is already {stage.value}", error_code="DEAL_ALREADY_CLOSED"
            )

    if stage == DealStage.CLOSED_LOST:
        if loss_reason is None:
            raise ValidationError(
                "loss_reason is required when closing a deal as lost",
                error_code="LOSS_REASON_REQUIRED",
            )
        try:
            reason = LossReason(loss_reason)
        except ValueError as exc:
            raise ValidationError("Unknown loss_reason", error_code="INVALID_LOSS_REASON") from exc
        db.add(
            DealOutcome(
                company_id=user.company_id,
                deal_id=deal.id,
                lead_id=deal.lead_id,
                outcome=Outcome.LOST,
                loss_reason=reason,
                closed_at=datetime.now(UTC),
            )
        )
    elif stage == DealStage.CLOSED_WON:
        db.add(
            DealOutcome(
                company_id=user.company_id,
                deal_id=deal.id,
                lead_id=deal.lead_id,
                outcome=Outcome.WON,
                closed_at=datetime.now(UTC),
            )
        )

    deal.stage = stage
    _enqueue_forecast(db, user=user, lead_id=deal.lead_id)
    await db.commit()
    await db.refresh(deal)
    return deal


async def pipeline_board(db: AsyncSession, *, user: User) -> list[dict]:
    """Kanban view: deals grouped by stage, prepared server-side.

    Totals are per (stage, currency). Summing a USD deal and an INR deal into
    one number would be meaningless, and there is no FX rate source here — so
    each currency is reported separately rather than silently added up.
    """

    deals = await list_deals(db, user=user)
    totals: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    grouped: dict[str, list[Deal]] = defaultdict(list)

    for deal in deals:
        grouped[deal.stage.value].append(deal)
        if deal.amount is not None:
            totals[deal.stage.value][deal.currency] += deal.amount

    return [
        {
            "stage": stage.value,
            "count": len(grouped[stage.value]),
            "totals_by_currency": dict(totals[stage.value]),
            "deals": grouped[stage.value],
        }
        for stage in DealStage
    ]
