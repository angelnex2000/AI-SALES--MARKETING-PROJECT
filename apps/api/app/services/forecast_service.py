"""Revenue forecasting: gather the pipeline, run the agent, store the result.

The agent never queries the database — the same rule the Campaign Agent
follows, so it stays runnable from a mock payload. This module answers "what
is in the pipeline", which is a SQL problem.

Three scoping decisions worth stating, because each is a way the number could
be silently wrong:

**No assigned-only filter.** Every other read in this codebase narrows a Sales
Executive to their own leads. A company revenue forecast must not: filtered to
one rep it would report a fraction of the pipeline as the whole. It is safe
because `POST /ai/forecast/run` and `GET /ai/forecast` are Admin/Manager only —
the isolation rule is enforced by who may ask, not by narrowing the answer.

**One forecast per currency.** `Deal.amount` is meaningless across currencies
without an FX source this service does not have, so a tenant selling in INR and
USD gets two rows. Summing them would produce a headline figure that is not
money.

**Committed revenue comes from `DealOutcome.closed_at`, not `Deal.stage`.**
The stage says a deal is won; only the outcome row says *when*, and a forecast
for August must count August's wins rather than every win to date.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.forecasting.model import RevenueForecastingAgent
from app.core.exceptions import ValidationError
from app.models.deal import Deal, DealStage
from app.models.feedback import DealOutcome, Outcome
from app.models.forecast import RevenueForecast
from app.models.lead import Lead

# How many completed periods of history to hand the agent for the trend arrow.
HISTORY_PERIODS = 6

# A forecast row is written per currency; without any deals at all there is
# nothing to forecast in, so this is what an empty workspace reports in.
FALLBACK_CURRENCY = "USD"


def period_bounds(period: str) -> tuple[datetime, datetime]:
    """Half-open [start, end) for `2026-08` or `2026-Q3`.

    Half-open on purpose: a closed interval would double-count a deal expected
    to close exactly at midnight on the boundary, in both the month it ends and
    the one it begins.
    """

    try:
        year_part, _, rest = period.partition("-")
        year = int(year_part)
        if rest.upper().startswith("Q"):
            quarter = int(rest[1:])
            if not 1 <= quarter <= 4:
                raise ValueError(period)
            start_month = (quarter - 1) * 3 + 1
            start = datetime(year, start_month, 1, tzinfo=UTC)
            end = (
                datetime(year + 1, 1, 1, tzinfo=UTC)
                if quarter == 4
                else datetime(year, start_month + 3, 1, tzinfo=UTC)
            )
            return start, end
        month = int(rest)
        if not 1 <= month <= 12:
            raise ValueError(period)
        start = datetime(year, month, 1, tzinfo=UTC)
        end = (
            datetime(year + 1, 1, 1, tzinfo=UTC)
            if month == 12
            else datetime(year, month + 1, 1, tzinfo=UTC)
        )
        return start, end
    except (ValueError, IndexError) as exc:
        raise ValidationError(
            f"forecast_period must be YYYY-MM or YYYY-Qn, got {period!r}",
            error_code="INVALID_FORECAST_PERIOD",
        ) from exc


def current_period(as_of: datetime | None = None) -> str:
    moment = as_of or datetime.now(UTC)
    return f"{moment.year:04d}-{moment.month:02d}"


def _previous_months(period: str, count: int) -> list[str]:
    """The `count` months immediately before `period`, oldest first."""

    year, _, rest = period.partition("-")
    if rest.upper().startswith("Q"):
        return []
    index = int(year) * 12 + int(rest) - 1
    return [f"{(index - k) // 12:04d}-{(index - k) % 12 + 1:02d}" for k in range(count, 0, -1)]


def _open_deals_stmt(company_id: uuid.UUID):
    """Open, non-archived deals on non-archived leads, tenant-scoped.

    Excludes deals whose parent lead is archived for the same reason
    `deal_service._visible` does: archiving a lead must remove its deals from
    every view, and a forecast that still counts them reports revenue from
    accounts nobody is working.
    """

    return (
        select(Deal)
        .join(Lead, Deal.lead_id == Lead.id)
        .where(
            Deal.company_id == company_id,
            Deal.archived_at.is_(None),
            Lead.archived_at.is_(None),
            Deal.stage.notin_((DealStage.CLOSED_WON, DealStage.CLOSED_LOST)),
        )
    )


async def _won_by_currency(
    db: AsyncSession, *, company_id: uuid.UUID, start: datetime, end: datetime
) -> dict[str, Decimal]:
    """Revenue actually banked in the window, per currency."""

    stmt = (
        select(Deal.currency, func.coalesce(func.sum(Deal.amount), 0))
        .join(DealOutcome, DealOutcome.deal_id == Deal.id)
        .join(Lead, Deal.lead_id == Lead.id)
        .where(
            Deal.company_id == company_id,
            Deal.archived_at.is_(None),
            Lead.archived_at.is_(None),
            DealOutcome.outcome == Outcome.WON,
            DealOutcome.closed_at >= start,
            DealOutcome.closed_at < end,
        )
        .group_by(Deal.currency)
    )
    return {currency: Decimal(str(total)) for currency, total in (await db.execute(stmt)).all()}


async def _history(
    db: AsyncSession, *, company_id: uuid.UUID, period: str, currency: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for past in _previous_months(period, HISTORY_PERIODS):
        start, end = period_bounds(past)
        won = await _won_by_currency(db, company_id=company_id, start=start, end=end)
        rows.append({"period": past, "won_revenue": str(won.get(currency, Decimal("0")))})
    return rows


async def generate_forecast(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    period: str | None = None,
    as_of: datetime | None = None,
) -> list[RevenueForecast]:
    """Compute and persist one forecast row per currency in play.

    Persisted rather than returned live because forecast accuracy is only
    measurable against a **stored, timestamped** prediction: comparing "what we
    said on 1 August" with what actually closed is impossible if the dashboard
    recomputes a different number on every page load.
    """

    moment = as_of or datetime.now(UTC)
    period = period or current_period(moment)
    start, end = period_bounds(period)

    open_deals = list((await db.execute(_open_deals_stmt(company_id))).scalars().all())
    committed = await _won_by_currency(db, company_id=company_id, start=start, end=end)

    currencies = sorted({d.currency for d in open_deals} | set(committed))
    if not currencies:
        currencies = [FALLBACK_CURRENCY]

    written: list[RevenueForecast] = []
    for currency in currencies:
        payload = {
            "forecast_period": period,
            "currency": currency,
            "period_start": start,
            "period_end": end,
            "as_of": moment,
            "committed_revenue": str(committed.get(currency, Decimal("0"))),
            "open_deals": [
                {
                    "id": str(deal.id),
                    "name": deal.name,
                    "stage": deal.stage.value,
                    "amount": None if deal.amount is None else str(deal.amount),
                    "expected_close_date": (
                        None if deal.expected_close_date is None else _utc(deal.expected_close_date)
                    ),
                }
                for deal in open_deals
                if deal.currency == currency
            ],
            "history": await _history(db, company_id=company_id, period=period, currency=currency),
        }
        result = await RevenueForecastingAgent().run(payload)

        forecast = RevenueForecast(
            company_id=company_id,
            forecast_period=period,
            currency=currency,
            predicted_revenue=Decimal(result["predicted_revenue"]),
            committed_revenue=Decimal(result["committed_revenue"]),
            weighted_pipeline=Decimal(result["weighted_pipeline"]),
            confidence=result["confidence"],
            model_name=result["model_name"],
            model_version=result["model_version"],
            explanation=result["explanation"],
            breakdown=result["breakdown"],
            input_summary=(
                f"{len(payload['open_deals'])} open deal(s) in {currency}; "
                f"calibration={result['calibration_source']}"
            ),
        )
        db.add(forecast)
        written.append(forecast)

    await db.commit()
    for forecast in written:
        await db.refresh(forecast)
    return written


def _utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes even for `DateTime(timezone=True)`, and
    the agent compares these against timezone-aware period bounds."""

    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def latest_forecasts(
    db: AsyncSession, *, company_id: uuid.UUID, period: str | None = None
) -> list[RevenueForecast]:
    """Most recent forecast per (period, currency).

    `revenue_forecasts` is append-only history, so every refresh adds rows;
    returning all of them would show a manager the same period several times
    with different numbers and no indication which is current.
    """

    stmt = select(RevenueForecast).where(RevenueForecast.company_id == company_id)
    if period is not None:
        stmt = stmt.where(RevenueForecast.forecast_period == period)
    rows = list(
        (await db.execute(stmt.order_by(RevenueForecast.created_at.desc()))).scalars().all()
    )

    latest: dict[tuple[str, str], RevenueForecast] = {}
    for row in rows:  # already newest-first
        latest.setdefault((row.forecast_period, row.currency), row)
    return sorted(latest.values(), key=lambda f: (f.forecast_period, f.currency))


async def forecast_history(
    db: AsyncSession, *, company_id: uuid.UUID
) -> list[RevenueForecast]:
    """The full append-only trail, for accuracy review after a period closes."""

    stmt = (
        select(RevenueForecast)
        .where(RevenueForecast.company_id == company_id)
        .order_by(RevenueForecast.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


__all__ = [
    "current_period",
    "forecast_history",
    "generate_forecast",
    "latest_forecasts",
    "period_bounds",
]
