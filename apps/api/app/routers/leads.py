import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services import lead_service
from app.tasks import run_lead_intelligence

router = APIRouter()


@router.get("/")
async def list_leads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await lead_service.list_leads(db, company_id=current_user.company_id, current_user=current_user)


@router.get("/{lead_id}")
async def get_lead(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    lead = await lead_service.get_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")
    return lead


@router.post("/{lead_id}/research", status_code=status.HTTP_202_ACCEPTED)
async def generate_research(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fire-and-poll: returns a job id immediately, a Celery worker runs the
    agents (see app/tasks.py, app/services/ai_orchestrator.py)."""

    lead = await lead_service.get_lead(
        db, lead_id=lead_id, company_id=current_user.company_id, current_user=current_user
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lead not found")

    job = Job(
        company_id=current_user.company_id,
        job_type="lead_intelligence",
        lead_id=lead.id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    run_lead_intelligence.delay(str(job.id), str(lead.id))
    return {"job_id": job.id, "status": job.status}