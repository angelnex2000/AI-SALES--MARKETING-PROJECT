"""Job status polling.

The frontend polls here after any 202 + job_id response, so this endpoint is
hit repeatedly and must stay cheap.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db
from app.models.user import User
from app.schemas.ai import JobResponse
from app.schemas.common import ok
from app.services import job_service

router = APIRouter()


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The path the frontend polls after any 202 + job_id. Shares
    job_service with GET /api/v1/ai/jobs/{job_id} so the two cannot drift."""

    job = await job_service.require_job(db, job_id=job_id, user=current_user)
    return ok(data=JobResponse.model_validate(job))
