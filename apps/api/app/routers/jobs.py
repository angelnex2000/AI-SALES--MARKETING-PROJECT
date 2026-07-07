import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.job import Job
from app.models.user import User

router = APIRouter()


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    job = await db.get(Job, job_id)
    if job is None or job.company_id != current_user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job