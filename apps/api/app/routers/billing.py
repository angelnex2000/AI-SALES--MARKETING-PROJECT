"""Module 10 (part 3) — Billing (Admin only).

Subscription/usage/invoices are read-only views; upgrade/cancel are
user-initiated but the authoritative state arrives via the provider-signed
webhook (no user auth, tenant resolved server-side).
"""


from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import require_role
from app.dependencies.db import get_db
from app.models.billing import BillingSubscription, UsageRecord
from app.models.user import Role, User
from app.schemas.common import ok

router = APIRouter()


@router.get("/subscription")
async def get_subscription(db: AsyncSession = Depends(get_db), user: User = Depends(require_role(Role.ADMIN))):
    row = await db.execute(
        select(BillingSubscription).where(BillingSubscription.company_id == user.company_id)
    )
    sub = row.scalar_one_or_none()
    if sub is None:
        return ok(data=None, message="No active subscription")
    return ok(
        data={
            "id": sub.id,
            "plan_name": sub.plan_name,
            "status": sub.status.value,
            "user_limit": sub.user_limit,
            "ai_credit_limit": sub.ai_credit_limit,
        }
    )


@router.get("/usage")
async def get_usage(db: AsyncSession = Depends(get_db), user: User = Depends(require_role(Role.ADMIN))):
    rows = await db.execute(select(UsageRecord).where(UsageRecord.company_id == user.company_id))
    records = rows.scalars().all()
    return ok(data={"records": len(records)})


@router.get("/invoices")
async def get_invoices(user: User = Depends(require_role(Role.ADMIN))):
    # Invoices originate provider-side; surfaced once the billing provider is wired.
    return ok(data=[], message="Invoices sourced from billing provider (pending)")


@router.post("/upgrade")
async def upgrade(user: User = Depends(require_role(Role.ADMIN))):
    return ok(message="Upgrade initiated (provider checkout pending)")


@router.post("/cancel")
async def cancel(user: User = Depends(require_role(Role.ADMIN))):
    return ok(message="Cancellation initiated (confirmed via webhook)")


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def billing_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Provider-signed, no user auth. Verify signature and resolve the tenant
    from the provider customer/subscription id — never trust the body's ids."""

    _ = await request.json()
    # TODO(security): verify provider signature; TODO: map customer -> company_id.
    return ok(message="Billing event received")
