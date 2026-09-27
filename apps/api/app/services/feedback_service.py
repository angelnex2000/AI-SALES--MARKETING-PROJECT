"""Feedback capture and the AI-quality report.

Two jobs, and the split matters:

**Capture** stores only explicit human judgement — a rating, a verdict, a
correction. It does not store "a meeting was booked" or "the deal closed",
because those are already `Meeting` and `DealOutcome` rows. A copy would go
stale the moment a meeting is cancelled, and this is the table a retraining
run reads: a stale label is a mislabelled training example, not a display bug.

**Derivation** joins those first-class facts back together at read time, along
with the implicit signals nobody has to stop and enter — the Gate 2
approve/reject split, how much of each draft a human rewrote, and how far each
stored forecast landed from what actually closed.

The agent does the judging; this module answers "what happened", which is a
SQL problem.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.feedback_learning import edit_distance
from agents.feedback_learning.agent import FeedbackLearningAgent
from app.core.exceptions import NotFoundError, ValidationError
from app.models.deal import Deal
from app.models.feedback import DealOutcome, FeedbackRecord, FeedbackTarget, Outcome
from app.models.forecast import RevenueForecast
from app.models.lead import BuyingSignal, ICPScore, Lead, LeadScore, ResearchReport
from app.models.outreach import DraftStatus, EmailDraft, ReplyIntentResult
from app.models.user import Role, User
from app.services import forecast_service, lead_service

# Which table each polymorphic target lives in. Used to verify a target exists
# and belongs to the caller's tenant before feedback is written against it —
# the check a real foreign key would otherwise give us.
TARGET_MODELS: dict[FeedbackTarget, Any] = {
    FeedbackTarget.EMAIL_DRAFT: EmailDraft,
    FeedbackTarget.RESEARCH_REPORT: ResearchReport,
    FeedbackTarget.LEAD_SCORE: LeadScore,
    FeedbackTarget.BUYING_SIGNAL: BuyingSignal,
    FeedbackTarget.ICP_SCORE: ICPScore,
    FeedbackTarget.REPLY_INTENT: ReplyIntentResult,
    FeedbackTarget.REVENUE_FORECAST: RevenueForecast,
}

# Targets that belong to the whole tenant rather than to one lead.
COMPANY_LEVEL_TARGETS = (FeedbackTarget.REVENUE_FORECAST,)


async def _resolve_target(
    db: AsyncSession, *, target_type: FeedbackTarget, target_id: uuid.UUID, user: User
) -> Any:
    """Load the AI output being rated, enforcing tenant scope.

    404 rather than 403 for another tenant's row, the codebase-wide rule: the
    caller must not learn the id exists. Lead-scoped targets additionally go
    through `lead_service.require_lead`, so a Sales Executive cannot rate — or
    by rating, confirm the existence of — output on a lead assigned to someone
    else.
    """

    model = TARGET_MODELS[target_type]
    row = await db.get(model, target_id)
    if row is None or row.company_id != user.company_id:
        raise NotFoundError("Feedback target not found", error_code="FEEDBACK_TARGET_NOT_FOUND")

    lead_id = getattr(row, "lead_id", None)
    if lead_id is not None:
        await lead_service.require_lead(
            db, lead_id=lead_id, company_id=user.company_id, current_user=user
        )
    return row


async def record_feedback(
    db: AsyncSession,
    *,
    user: User,
    target_type: FeedbackTarget,
    target_id: uuid.UUID,
    rating: int | None = None,
    verdict: Any = None,
    correction: str | None = None,
    comment: str | None = None,
    details: dict[str, Any] | None = None,
) -> FeedbackRecord:
    """Record one person's judgement of one AI output.

    **Updates the author's existing row rather than appending.** Every AI
    *output* table in this codebase is append-only, but this is human input and
    a rating is a current opinion, not an event: without this, one enthusiastic
    user clicking five stars ten times would move an aggregate that feeds a
    retraining decision. The correction history that would matter is already
    kept — the AI outputs themselves are versioned.
    """

    if rating is None and verdict is None and correction is None:
        raise ValidationError(
            "Feedback must carry at least a rating, a verdict, or a correction",
            error_code="EMPTY_FEEDBACK",
        )

    target = await _resolve_target(db, target_type=target_type, target_id=target_id, user=user)

    existing = (
        await db.execute(
            select(FeedbackRecord).where(
                FeedbackRecord.company_id == user.company_id,
                FeedbackRecord.target_type == target_type,
                FeedbackRecord.target_id == target_id,
                FeedbackRecord.author_id == user.id,
            )
        )
    ).scalar_one_or_none()

    record = existing or FeedbackRecord(
        company_id=user.company_id,
        target_type=target_type,
        target_id=target_id,
        lead_id=getattr(target, "lead_id", None),
        author_id=user.id,
    )
    record.rating = rating
    record.verdict = verdict
    record.correction = correction
    record.comment = comment
    record.details = details
    if existing is None:
        db.add(record)

    await db.commit()
    await db.refresh(record)
    return record


def _visible(stmt, *, user: User):
    """Feedback inherits the visibility of the lead it concerns.

    Company-level feedback (a forecast rating) has no lead, so it is visible to
    anyone who can already read the forecast — enforced by the router's role
    gate, since a Sales Executive cannot reach those endpoints at all.
    """

    stmt = stmt.where(FeedbackRecord.company_id == user.company_id)
    if user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.outerjoin(Lead, FeedbackRecord.lead_id == Lead.id).where(
            (FeedbackRecord.lead_id.is_(None)) | (Lead.owner_id == user.id)
        )
    return stmt


async def list_feedback(
    db: AsyncSession,
    *,
    user: User,
    target_type: FeedbackTarget | None = None,
    lead_id: uuid.UUID | None = None,
) -> list[FeedbackRecord]:
    stmt = _visible(select(FeedbackRecord), user=user)
    if target_type is not None:
        stmt = stmt.where(FeedbackRecord.target_type == target_type)
    if lead_id is not None:
        await lead_service.require_lead(
            db, lead_id=lead_id, company_id=user.company_id, current_user=user
        )
        stmt = stmt.where(FeedbackRecord.lead_id == lead_id)
    return list(
        (await db.execute(stmt.order_by(FeedbackRecord.created_at.desc()))).scalars().all()
    )


# ------------------------------------------------------------- derived signal


async def _draft_counts(db: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    """Gate 2 outcomes — the acceptance signal, free of charge."""

    rows = (
        await db.execute(
            select(EmailDraft.status, func.count())
            .where(EmailDraft.company_id == company_id, EmailDraft.ai_generated.is_(True))
            .group_by(EmailDraft.status)
        )
    ).all()
    counts = {status.value: 0 for status in DraftStatus}
    for status, total in rows:
        counts[status.value if hasattr(status, "value") else str(status)] = total
    # A sent draft was approved first; counting only `approved` would make the
    # acceptance rate fall every time someone actually sends an email.
    counts["approved"] += counts.get("sent", 0)
    return counts


async def _edits(db: AsyncSession, company_id: uuid.UUID) -> list[dict[str, Any]]:
    """Per-draft human divergence, for drafts whose AI original survives."""

    drafts = (
        (
            await db.execute(
                select(EmailDraft).where(
                    EmailDraft.company_id == company_id,
                    EmailDraft.ai_generated.is_(True),
                    EmailDraft.ai_original_body.isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "draft_id": str(draft.id),
            "lead_id": str(draft.lead_id),
            **edit_distance.measure(
                original_subject=draft.ai_original_subject,
                original_body=draft.ai_original_body,
                final_subject=draft.subject,
                final_body=draft.body,
            ),
        }
        for draft in drafts
    ]


async def _reply_intent_review(db: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    """Ground truth for reply intent exists only where a human said so.

    A `correction` that matches the stored label is a confirmation; one that
    differs is a correction. Classifications nobody looked at are excluded —
    counting them as correct would manufacture a 99% accuracy out of silence.
    """

    rows = (
        await db.execute(
            select(FeedbackRecord.target_id, FeedbackRecord.correction, ReplyIntentResult.intent)
            .join(ReplyIntentResult, ReplyIntentResult.id == FeedbackRecord.target_id)
            .where(
                FeedbackRecord.company_id == company_id,
                FeedbackRecord.target_type == FeedbackTarget.REPLY_INTENT,
                FeedbackRecord.correction.isnot(None),
            )
        )
    ).all()
    confirmed = sum(
        1 for _, correction, intent in rows if str(correction) == str(getattr(intent, "value", intent))
    )
    return {"reviewed": len(rows), "confirmed": confirmed}


async def _forecast_errors(db: AsyncSession, company_id: uuid.UUID) -> list[dict[str, Any]]:
    """Stored predictions against what actually closed.

    The only metric here with real ground truth, and the reason
    `revenue_forecasts` is append-only rather than a recomputed dashboard
    figure: comparing "what we said on 1 August" with what August delivered is
    impossible if the number is regenerated on every page load.
    """

    forecasts = await forecast_service.latest_forecasts(db, company_id=company_id)
    now = datetime.now(UTC)
    errors: list[dict[str, Any]] = []

    for forecast in forecasts:
        try:
            start, end = forecast_service.period_bounds(forecast.forecast_period)
        except ValidationError:
            continue
        # `deal_outcomes` records that a deal closed and when; the money lives
        # on the deal, so the actual is summed across the join.
        actual = (
            await db.execute(
                select(func.coalesce(func.sum(Deal.amount), 0))
                .select_from(DealOutcome)
                .join(Deal, Deal.id == DealOutcome.deal_id)
                .where(
                    DealOutcome.company_id == company_id,
                    DealOutcome.outcome == Outcome.WON,
                    DealOutcome.closed_at >= start,
                    DealOutcome.closed_at < end,
                    Deal.currency == forecast.currency,
                )
            )
        ).scalar()
        actual = Decimal(str(actual or 0))
        predicted = Decimal(forecast.predicted_revenue)
        errors.append(
            {
                "forecast_period": forecast.forecast_period,
                "currency": forecast.currency,
                "predicted": str(predicted),
                "actual": str(actual),
                # A period still running has no actual to compare against;
                # scoring it would report a huge error simply because the month
                # is not over.
                "period_closed": end <= now,
                "absolute_percentage_error": (
                    float(abs(predicted - actual) / actual) if actual else None
                ),
            }
        )
    return [e for e in errors if e["absolute_percentage_error"] is not None]


async def _ratings_by_target(db: AsyncSession, company_id: uuid.UUID) -> dict[str, list[int]]:
    rows = (
        await db.execute(
            select(FeedbackRecord.target_type, FeedbackRecord.rating).where(
                FeedbackRecord.company_id == company_id, FeedbackRecord.rating.isnot(None)
            )
        )
    ).all()
    grouped: dict[str, list[int]] = {}
    for target_type, rating in rows:
        key = getattr(target_type, "value", str(target_type))
        grouped.setdefault(key, []).append(int(rating))
    return grouped


async def quality_report(db: AsyncSession, *, company_id: uuid.UUID) -> dict[str, Any]:
    """The Admin dashboard's AI-quality panel."""

    drafts = await _draft_counts(db, company_id)
    edits = await _edits(db, company_id)
    intents = await _reply_intent_review(db, company_id)
    errors = await _forecast_errors(db, company_id)
    ratings = await _ratings_by_target(db, company_id)

    return await FeedbackLearningAgent().run(
        {
            "drafts": drafts,
            "edits": edits,
            "reply_intent": intents,
            "forecast_errors": errors,
            "ratings_by_target": ratings,
            "training_samples": {
                "outreach": len(edits),
                "reply_intent": intents["reviewed"],
                "lead_scoring": await _closed_deal_count(db, company_id),
                "revenue_forecasting": sum(1 for e in errors if e["period_closed"]),
            },
        }
    )


async def _closed_deal_count(db: AsyncSession, company_id: uuid.UUID) -> int:
    """Won/lost outcomes are the supervised labels lead scoring retrains on."""

    return (
        await db.execute(
            select(func.count()).select_from(DealOutcome).where(DealOutcome.company_id == company_id)
        )
    ).scalar() or 0


__all__ = [
    "list_feedback",
    "quality_report",
    "record_feedback",
]
