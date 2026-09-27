"""Module 5 — Deals & CRM Pipeline.

Mounted at `/api/v1` (not `/deals`) because it owns both `/deals/*` and
`/pipeline/*`. A Deal is a qualified opportunity against a Lead (1 Lead : N
Deal); its owner derives from the parent lead, so isolation is always checked
through the lead. All decisions live in `deal_service`.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.deal import DealStage
from app.models.user import Role, User
from app.schemas.common import ok
from app.schemas.deal import (
    DealCreate,
    DealResponse,
    DealStageUpdate,
    DealUpdate,
    PipelineColumn,
)
from app.services import deal_service

router = APIRouter()

_WRITERS = (Role.SALES_MANAGER, Role.SALES_EXECUTIVE)


# ----------------------------------------------------------------------- /deals


@router.get("/deals")
async def list_deals(
    stage: DealStage | None = None,
    lead_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    deals = await deal_service.list_deals(db, user=user, stage=stage, lead_id=lead_id)
    return ok(data=[DealResponse.model_validate(d) for d in deals])


@router.post("/deals", status_code=status.HTTP_201_CREATED)
async def create_deal(
    payload: DealCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    deal = await deal_service.create_deal(db, data=payload.model_dump(), user=user)
    return ok(data=DealResponse.model_validate(deal), message="Deal created successfully")


@router.get("/deals/{deal_id}")
async def get_deal(
    deal_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    deal = await deal_service.require_deal(db, deal_id=deal_id, user=user)
    return ok(data=DealResponse.model_validate(deal))


@router.put("/deals/{deal_id}")
async def update_deal(
    deal_id: uuid.UUID,
    payload: DealUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    # exclude_unset, not exclude_none — sending "expected_close_date": null
    # must clear the date rather than being silently dropped. Stage is not
    # editable here: it is a business event, see PATCH /deals/{id}/stage.
    deal = await deal_service.update_deal(
        db, deal_id=deal_id, changes=payload.model_dump(exclude_unset=True), user=user
    )
    return ok(data=DealResponse.model_validate(deal), message="Deal updated")


@router.delete("/deals/{deal_id}")
async def delete_deal(
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_MANAGER)),
):
    await deal_service.archive_deal(db, deal_id=deal_id, user=user)
    return ok(message="Deal archived")


@router.patch("/deals/{deal_id}/stage")
async def change_stage(
    deal_id: uuid.UUID,
    payload: DealStageUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    deal = await deal_service.change_stage(
        db, deal_id=deal_id, stage=payload.stage, loss_reason=payload.loss_reason, user=user
    )
    return ok(data=DealResponse.model_validate(deal), message="Stage updated")


# -------------------------------------------------------------------- /pipeline


@router.get("/pipeline/stages")
async def pipeline_stages(_: User = Depends(get_current_user)):
    """The fixed stage enum — constant, not a per-tenant table."""

    return ok(data=[s.value for s in DealStage])


@router.get("/pipeline/board")
async def pipeline_board(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    board = await deal_service.pipeline_board(db, user=user)
    return ok(data=[PipelineColumn.model_validate(col) for col in board])
