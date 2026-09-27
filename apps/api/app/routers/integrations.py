"""Module 10 (part 2) — Integrations & CRM Webhooks.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.dependencies.auth import require_role
from app.dependencies.db import get_db
from app.models.integration import (
    ConnectionStatus,
    Integration,
    IntegrationProvider,
    IntegrationSyncLog,
    IntegrationType,
)
from app.models.job import Job, JobStatus
from app.models.user import Role, User
from app.schemas.common import ok

router = APIRouter()


class ConnectRequest(BaseModel):
    provider: IntegrationProvider
    integration_type: IntegrationType


class IntegrationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    integration_type: IntegrationType
    provider: IntegrationProvider
    status: ConnectionStatus


class WebhookPayload(BaseModel):
    event_type: str = "contact.created"
    company_name: str
    contact_name: str | None = None
    email: str | None = None
    industry: str | None = None
    employees: int | None = None


async def _load(db: AsyncSession, integration_id: uuid.UUID, user: User) -> Integration:
    integration = await db.get(Integration, integration_id)
    if integration is None or integration.company_id != user.company_id:
        raise NotFoundError("Integration not found", error_code="INTEGRATION_NOT_FOUND")
    return integration


@router.get("/")
async def list_integrations(
    db: AsyncSession = Depends(get_db), user: User = Depends(require_role(Role.ADMIN))
):
    rows = await db.execute(select(Integration).where(Integration.company_id == user.company_id))
    return ok(data=[IntegrationResponse.model_validate(i) for i in rows.scalars().all()])


@router.post("/connect", status_code=status.HTTP_201_CREATED)
async def connect(
    payload: ConnectRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    integration = Integration(
        company_id=user.company_id,
        integration_type=payload.integration_type,
        provider=payload.provider,
        status=ConnectionStatus.DISCONNECTED,
    )
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    auth_url = f"https://auth.example/{payload.provider.value}/authorize?state={integration.id}"
    return ok(data={"integration_id": integration.id, "authorization_url": auth_url})


@router.get("/oauth/callback")
async def oauth_callback(
    state: uuid.UUID,
    code: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    integration = await _load(db, state, user)
    integration.status = ConnectionStatus.CONNECTED
    await db.commit()
    return ok(message="Integration connected")


@router.post("/{integration_id}/disconnect")
async def disconnect(
    integration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    integration = await _load(db, integration_id, user)
    integration.status = ConnectionStatus.DISCONNECTED
    integration.access_token_encrypted = None
    integration.refresh_token_encrypted = None
    await db.commit()
    return ok(message="Integration disconnected")


@router.post("/{integration_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync(
    integration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    await _load(db, integration_id, user)
    job = Job(company_id=user.company_id, job_type="crm_sync", status=JobStatus.PENDING)
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return ok(data={"job_id": job.id, "status": job.status}, message="Sync started")


@router.get("/{integration_id}/sync-logs")
async def sync_logs(
    integration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN)),
):
    await _load(db, integration_id, user)
    rows = await db.execute(
        select(IntegrationSyncLog).where(IntegrationSyncLog.integration_id == integration_id)
    )
    return ok(
        data=[
            {"id": s.id, "sync_type": s.sync_type, "status": s.status.value, "records_processed": s.records_processed}
            for s in rows.scalars().all()
        ]
    )


@router.post("/webhooks/hubspot", status_code=status.HTTP_200_OK)
async def hubspot_webhook(payload: WebhookPayload, db: AsyncSession = Depends(get_db)):
    """Inbound webhook receiver from HubSpot CRM."""
    return ok(data={"provider": "hubspot", "processed": True, "event": payload.event_type, "company": payload.company_name})


@router.post("/webhooks/salesforce", status_code=status.HTTP_200_OK)
async def salesforce_webhook(payload: WebhookPayload, db: AsyncSession = Depends(get_db)):
    """Inbound webhook receiver from Salesforce CRM."""
    return ok(data={"provider": "salesforce", "processed": True, "event": payload.event_type, "company": payload.company_name})
