"""Module 10 (part 1) — Analytics.

Content is scoped by role: a Sales Exec's numbers cover only their assigned
leads; revenue and team-performance are Manager/Admin only. All aggregation
lives in `analytics_service`, which also applies the archived filters — so
the dashboard can never disagree with the list pages beside it.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.user import Role, User
from app.schemas.analytics import (
    DashboardMetrics,
    FunnelStage,
    RevenueSummary,
    TeamMemberPerformance,
)
from app.schemas.common import ok
from app.services import analytics_service

router = APIRouter()


@router.get("/dashboard")
async def dashboard(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    metrics = await analytics_service.dashboard_metrics(db, user=user)
    return ok(data=DashboardMetrics.model_validate(metrics))


@router.get("/leads")
async def lead_analytics(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return ok(data=await analytics_service.leads_by_status(db, user=user))


@router.get("/funnel")
async def funnel(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    stages = await analytics_service.lead_funnel(db, user=user)
    return ok(data=[FunnelStage.model_validate(s) for s in stages])


@router.get("/campaigns")
async def campaign_analytics(user: User = Depends(get_current_user)):
    # Campaign performance aggregation lands with the outreach/tracking pipeline.
    return ok(data={"campaigns": [], "note": "aggregation pending outreach tracking"})


@router.get("/revenue")
async def revenue_analytics(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    summary = await analytics_service.revenue_summary(db, user=user)
    return ok(data=RevenueSummary.model_validate(summary))


@router.get("/team-performance")
async def team_performance(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    rows = await analytics_service.team_performance(db, user=user)
    return ok(data=[TeamMemberPerformance.model_validate(r) for r in rows])
