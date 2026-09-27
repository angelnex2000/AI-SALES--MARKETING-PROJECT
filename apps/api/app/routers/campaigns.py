"""Module 6 (part 1) — Campaigns & Templates.

Create/edit = Marketing (owns Campaign Studio); Admin is read-only; Manager
gets an approve action. Templates are reusable and versioned — editing creates
a new version row rather than mutating in place.
"""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.campaign import Campaign, CampaignStatus, CampaignTemplate, TemplateStatus
from app.models.user import Role, User
from app.schemas.common import ok

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    description: str | None = None
    target_industry: str | None = None
    target_region: str | None = None
    goal: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    target_industry: str | None
    target_region: str | None
    goal: str | None
    status: CampaignStatus
    start_date: date | None
    end_date: date | None


class TemplateCreate(BaseModel):
    name: str
    subject: str
    body: str


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    subject: str
    body: str
    version: int
    status: TemplateStatus


# --------------------------------------------------------------------- campaigns


@router.get("/")
async def list_campaigns(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = await db.execute(select(Campaign).where(Campaign.company_id == user.company_id))
    return ok(data=[CampaignResponse.model_validate(c) for c in rows.scalars().all()])


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING)),
):
    campaign = Campaign(
        company_id=user.company_id, created_by_user_id=user.id, **payload.model_dump(exclude_none=True)
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return ok(data=CampaignResponse.model_validate(campaign), message="Campaign created")


@router.get("/{campaign_id}")
async def get_campaign(
    campaign_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    campaign = await _load(db, campaign_id, user)
    return ok(data=CampaignResponse.model_validate(campaign))


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING)),
):
    campaign = await _load(db, campaign_id, user)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(campaign, field, value)
    await db.commit()
    await db.refresh(campaign)
    return ok(data=CampaignResponse.model_validate(campaign), message="Campaign updated")


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING)),
):
    campaign = await _load(db, campaign_id, user)
    await db.delete(campaign)
    await db.commit()
    return ok(message="Campaign deleted")


@router.post("/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_MANAGER)),
):
    campaign = await _load(db, campaign_id, user)
    campaign.status = CampaignStatus.ACTIVE
    await db.commit()
    return ok(message="Campaign approved")


# --------------------------------------------------------------------- templates


@router.get("/templates/all")
async def list_templates(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = await db.execute(select(CampaignTemplate).where(CampaignTemplate.company_id == user.company_id))
    return ok(data=[TemplateResponse.model_validate(t) for t in rows.scalars().all()])


@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING)),
):
    template = CampaignTemplate(company_id=user.company_id, version=1, **payload.model_dump())
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return ok(data=TemplateResponse.model_validate(template), message="Template created")


@router.put("/templates/{template_id}")
async def version_template(
    template_id: uuid.UUID,
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.MARKETING)),
):
    """Editing a template creates a NEW version row — sent emails must keep
    pointing at the exact version they used."""

    current = await db.get(CampaignTemplate, template_id)
    if current is None or current.company_id != user.company_id:
        raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND")
    new_version = CampaignTemplate(
        company_id=user.company_id, version=current.version + 1, **payload.model_dump()
    )
    db.add(new_version)
    await db.commit()
    await db.refresh(new_version)
    return ok(data=TemplateResponse.model_validate(new_version), message="New template version created")


async def _load(db: AsyncSession, campaign_id: uuid.UUID, user: User) -> Campaign:
    campaign = await db.get(Campaign, campaign_id)
    if campaign is None or campaign.company_id != user.company_id:
        raise NotFoundError("Campaign not found", error_code="CAMPAIGN_NOT_FOUND")
    return campaign
