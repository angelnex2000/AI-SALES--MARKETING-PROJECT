"""Campaign planning: audience selection and plan persistence.

The agent decides strategy; this module answers "who". That split exists
because audience selection is a SQL problem — it needs the tenant's leads,
their latest scores and their signals — and agents deliberately never touch
the database.

Two rules shape the selection query:

**"Not yet scored" is not "scored badly".** A lead that has never been through
the intelligence pipeline has no `LeadScore` row. An inner join silently drops
it, so a brand-new workspace — where nothing has been scored — produces an
empty audience for every campaign with no explanation. The joins are outer,
and `include_unscored` decides explicitly.

**An empty audience is a first-class outcome.** It is the most common real
result, and "0 leads" alone is unactionable. `select_audience` counts how many
leads each criterion eliminates and reports the tightest one, so the Campaign
Studio can say *which* filter to relax.
"""

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.campaign import rules
from app.models.lead import BuyingSignal, ICPScore, Lead, LeadScore


async def _latest_scores(db: AsyncSession, company_id: uuid.UUID) -> dict[uuid.UUID, float]:
    """Most recent lead score per lead. `lead_scores` is append-only history,
    so an unaggregated join would multiply a lead by its scoring runs."""

    newest = (
        select(LeadScore.lead_id, func.max(LeadScore.created_at).label("newest"))
        .where(LeadScore.company_id == company_id)
        .group_by(LeadScore.lead_id)
        .subquery()
    )
    stmt = select(LeadScore.lead_id, LeadScore.score).join(
        newest,
        (LeadScore.lead_id == newest.c.lead_id) & (LeadScore.created_at == newest.c.newest),
    )
    return {lead_id: float(score) for lead_id, score in (await db.execute(stmt)).all()}


async def _latest_icp(db: AsyncSession, company_id: uuid.UUID) -> dict[uuid.UUID, float]:
    newest = (
        select(ICPScore.lead_id, func.max(ICPScore.created_at).label("newest"))
        .where(ICPScore.company_id == company_id)
        .group_by(ICPScore.lead_id)
        .subquery()
    )
    stmt = select(ICPScore.lead_id, ICPScore.overall_score).join(
        newest,
        (ICPScore.lead_id == newest.c.lead_id) & (ICPScore.created_at == newest.c.newest),
    )
    return {lead_id: float(score) for lead_id, score in (await db.execute(stmt)).all()}


async def _signal_counts(db: AsyncSession, company_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Distinct signal *types* per lead, not rows — `buying_signals` is
    append-only, so counting rows would reward re-running the pipeline."""

    stmt = (
        select(BuyingSignal.lead_id, func.count(func.distinct(BuyingSignal.signal_type)))
        .where(BuyingSignal.company_id == company_id)
        .group_by(BuyingSignal.lead_id)
    )
    return {lead_id: int(count) for lead_id, count in (await db.execute(stmt)).all()}


async def select_audience(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    industry: str | None = None,
    region: str | None = None,
    min_employees: int | None = None,
    criteria: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the matching lead ids plus why the rest were excluded."""

    resolved = rules.resolve_criteria(criteria)

    stmt = select(Lead).where(Lead.company_id == company_id, Lead.archived_at.is_(None))
    if industry:
        stmt = stmt.where(func.lower(Lead.industry) == industry.lower())
    if region:
        stmt = stmt.where(func.lower(Lead.country) == region.lower())
    if min_employees is not None:
        stmt = stmt.where(Lead.employees >= min_employees)

    candidates = list((await db.execute(stmt)).scalars().all())
    scores = await _latest_scores(db, company_id)
    icp = await _latest_icp(db, company_id)
    signals = await _signal_counts(db, company_id)

    selected: list[uuid.UUID] = []
    # Counted per criterion so the UI can say which filter to relax, rather
    # than reporting a bare zero.
    eliminated = {"lead_score": 0, "icp_score": 0, "buying_signals": 0, "unscored": 0}

    for lead in candidates:
        score = scores.get(lead.id)
        icp_score = icp.get(lead.id)
        signal_count = signals.get(lead.id, 0)

        if score is None and icp_score is None:
            if not resolved["include_unscored"]:
                eliminated["unscored"] += 1
                continue
        else:
            if score is not None and score < resolved["min_lead_score"]:
                eliminated["lead_score"] += 1
                continue
            if icp_score is not None and icp_score < resolved["min_icp_score"]:
                eliminated["icp_score"] += 1
                continue
        if signal_count < resolved["min_buying_signals"]:
            eliminated["buying_signals"] += 1
            continue
        selected.append(lead.id)

    limiting = max(eliminated, key=lambda k: eliminated[k]) if any(eliminated.values()) else None

    return {
        "considered": len(candidates),
        "selected": len(selected[: resolved["max_audience"]]),
        "lead_ids": [str(i) for i in selected[: resolved["max_audience"]]],
        "eliminated": eliminated,
        "limiting_criterion": limiting,
        "criteria": resolved,
        "truncated": len(selected) > resolved["max_audience"],
    }
