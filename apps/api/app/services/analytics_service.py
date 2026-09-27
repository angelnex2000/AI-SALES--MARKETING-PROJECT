"""Dashboard analytics.

Analytics is summarised business meaning, not raw data — so the rules that
govern the underlying records have to hold here too, or the numbers contradict
the pages they sit next to:

  * **Archived leads, contacts and deals are excluded.** A lead the user
    archived must not keep inflating "total leads".
  * **Assigned-only applies.** A Sales Executive's dashboard counts their own
    leads; a Manager's counts the whole tenant. Same rule as every list view.
  * **Money stays `Decimal` and is reported per currency.** Summing USD and
    INR into one "pipeline value" produces a number that means nothing, and
    there is no FX source here (same reasoning as `deal_service.pipeline_board`).

Counts are computed with conditional aggregation (`SUM(CASE WHEN ...)`) rather
than one query per metric, so the dashboard is a handful of round trips
instead of one per card.
"""

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deal import Deal, DealStage
from app.models.job import Job, JobStatus
from app.models.lead import Lead, LeadPriority
from app.models.meeting import Meeting, MeetingStatus
from app.models.user import Role, User

CLOSED_STAGES = (DealStage.CLOSED_WON, DealStage.CLOSED_LOST)


def _scope_leads(stmt: Select, *, user: User) -> Select:
    """Tenant + archived + assigned-only, applied to any statement whose FROM
    includes `leads`."""

    stmt = stmt.where(Lead.company_id == user.company_id, Lead.archived_at.is_(None))
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == user.id)
    return stmt


def _count_if(condition) -> object:
    """Portable conditional count. `func.count().filter()` needs SQLite >= 3.30;
    SUM(CASE ...) works everywhere and returns the same number."""

    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


async def dashboard_metrics(db: AsyncSession, *, user: User) -> dict:
    # --- leads: one pass, three numbers -------------------------------------
    lead_row = (
        await db.execute(
            _scope_leads(
                select(
                    func.count().label("total"),
                    _count_if(Lead.priority == LeadPriority.HIGH).label("high_priority"),
                    _count_if(Lead.owner_id.is_(None)).label("unassigned"),
                ).select_from(Lead),
                user=user,
            )
        )
    ).one()

    # --- deals: counts in one pass ------------------------------------------
    deal_row = (
        await db.execute(
            _scope_leads(
                select(
                    _count_if(Deal.stage.notin_(CLOSED_STAGES)).label("open"),
                    _count_if(Deal.stage == DealStage.CLOSED_WON).label("won"),
                    _count_if(Deal.stage == DealStage.CLOSED_LOST).label("lost"),
                )
                .select_from(Deal)
                .join(Lead, Deal.lead_id == Lead.id)
                .where(Deal.archived_at.is_(None)),
                user=user,
            )
        )
    ).one()

    # --- money: grouped by currency, never summed across them ---------------
    pipeline_rows = (
        await db.execute(
            _scope_leads(
                select(Deal.currency, func.coalesce(func.sum(Deal.amount), 0))
                .select_from(Deal)
                .join(Lead, Deal.lead_id == Lead.id)
                .where(Deal.archived_at.is_(None), Deal.stage.notin_(CLOSED_STAGES))
                .group_by(Deal.currency),
                user=user,
            )
        )
    ).all()
    won_rows = (
        await db.execute(
            _scope_leads(
                select(Deal.currency, func.coalesce(func.sum(Deal.amount), 0))
                .select_from(Deal)
                .join(Lead, Deal.lead_id == Lead.id)
                .where(Deal.archived_at.is_(None), Deal.stage == DealStage.CLOSED_WON)
                .group_by(Deal.currency),
                user=user,
            )
        )
    ).all()

    # --- meetings: only ones still on the calendar --------------------------
    meetings_scheduled = await db.scalar(
        _scope_leads(
            select(func.count())
            .select_from(Meeting)
            .join(Lead, Meeting.lead_id == Lead.id)
            .where(Meeting.status == MeetingStatus.SCHEDULED),
            user=user,
        )
    )

    # --- AI jobs: tenant-wide, not lead-scoped ------------------------------
    # Jobs are not all tied to a lead (forecasting is pipeline-wide), so they
    # cannot go through _scope_leads.
    job_row = (
        await db.execute(
            select(
                _count_if(Job.status == JobStatus.COMPLETED).label("completed"),
                _count_if(Job.status == JobStatus.FAILED).label("failed"),
                _count_if(Job.status.in_((JobStatus.PENDING, JobStatus.RUNNING))).label("in_flight"),
            ).where(Job.company_id == user.company_id)
        )
    ).one()

    return {
        "total_leads": lead_row.total or 0,
        "high_priority_leads": lead_row.high_priority or 0,
        "unassigned_leads": lead_row.unassigned or 0,
        "open_deals": deal_row.open or 0,
        "won_deals": deal_row.won or 0,
        "lost_deals": deal_row.lost or 0,
        "pipeline_value_by_currency": {c: Decimal(v) for c, v in pipeline_rows},
        "won_value_by_currency": {c: Decimal(v) for c, v in won_rows},
        "meetings_scheduled": meetings_scheduled or 0,
        "ai_jobs_completed": job_row.completed or 0,
        "ai_jobs_failed": job_row.failed or 0,
        "ai_jobs_in_flight": job_row.in_flight or 0,
        "generated_at": datetime.now(UTC),
    }


async def leads_by_status(db: AsyncSession, *, user: User) -> dict[str, int]:
    rows = await db.execute(
        _scope_leads(
            select(Lead.status, func.count()).select_from(Lead).group_by(Lead.status), user=user
        )
    )
    return {status.value: count for status, count in rows.all()}


async def revenue_summary(db: AsyncSession, *, user: User) -> dict:
    """Manager/Admin only (enforced at the router). Reported per currency for
    the same reason as the dashboard."""

    def _by_currency(*conditions) -> Select:
        return (
            select(Deal.currency, func.coalesce(func.sum(Deal.amount), 0))
            .where(Deal.company_id == user.company_id, Deal.archived_at.is_(None), *conditions)
            .group_by(Deal.currency)
        )

    won = (await db.execute(_by_currency(Deal.stage == DealStage.CLOSED_WON))).all()
    pipeline = (await db.execute(_by_currency(Deal.stage.notin_(CLOSED_STAGES)))).all()
    return {
        "closed_won_by_currency": {c: Decimal(v) for c, v in won},
        "open_pipeline_by_currency": {c: Decimal(v) for c, v in pipeline},
    }


async def team_performance(db: AsyncSession, *, user: User) -> list[dict]:
    """Per-rep counts. Grouped on the user so the response carries names rather
    than bare UUIDs the caller would have to resolve itself."""

    open_leads = _count_if(Lead.archived_at.is_(None))
    rows = await db.execute(
        select(
            User.id,
            User.full_name,
            User.role,
            func.count(Lead.id).label("total_leads"),
            open_leads.label("active_leads"),
        )
        .select_from(User)
        .outerjoin(Lead, (Lead.owner_id == User.id) & (Lead.company_id == user.company_id))
        .where(User.company_id == user.company_id, User.is_active.is_(True))
        .group_by(User.id, User.full_name, User.role)
        .order_by(User.full_name)
    )
    return [
        {
            "user_id": str(uid),
            "full_name": name,
            "role": role.value,
            "total_leads": total or 0,
            "active_leads": active or 0,
        }
        for uid, name, role, total, active in rows.all()
    ]


async def lead_funnel(db: AsyncSession, *, user: User) -> list[dict]:
    """Deal counts per pipeline stage, in stage order — every stage present
    even at zero, so the frontend renders a stable funnel rather than one that
    changes shape as data arrives."""

    rows = await db.execute(
        _scope_leads(
            select(Deal.stage, func.count())
            .select_from(Deal)
            .join(Lead, Deal.lead_id == Lead.id)
            .where(Deal.archived_at.is_(None))
            .group_by(Deal.stage),
            user=user,
        )
    )
    counts: dict[str, int] = defaultdict(int)
    for stage, count in rows.all():
        counts[stage.value] = count
    return [{"stage": s.value, "count": counts[s.value]} for s in DealStage]


__all__ = [
    "dashboard_metrics",
    "lead_funnel",
    "leads_by_status",
    "revenue_summary",
    "team_performance",
]
