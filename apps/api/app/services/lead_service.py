import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead
from app.models.user import Role, User


async def list_leads(db: AsyncSession, *, company_id: uuid.UUID, current_user: User) -> list[Lead]:
    """Tenant isolation and assigned-leads-only are both enforced here, not
    just hidden in the UI: a Sales Executive querying this never sees
    another rep's leads, and no query here can cross a company_id boundary.
    """

    stmt = select(Lead).where(Lead.company_id == company_id)
    if current_user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == current_user.id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, company_id: uuid.UUID, current_user: User
) -> Lead | None:
    stmt = select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
    if current_user.role == Role.SALES_EXECUTIVE:
        stmt = stmt.where(Lead.owner_id == current_user.id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def assign_lead(
    db: AsyncSession, *, lead_id: uuid.UUID, company_id: uuid.UUID, owner_id: uuid.UUID
) -> Lead | None:
    lead = await db.get(Lead, lead_id)
    if lead is None or lead.company_id != company_id:
        return None
    lead.owner_id = owner_id
    await db.commit()
    await db.refresh(lead)
    return lead