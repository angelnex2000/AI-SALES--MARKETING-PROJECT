"""Background AI job lifecycle.

Every slow agent call follows the same shape: create a Job row, hand the work
to Celery, return 202 + job_id, let the frontend poll. Two failure modes that
are easy to miss are handled here rather than in each router:

  * **Enqueue can fail.** The Job row is committed before Celery is told about
    it, so if Redis is unreachable the request would 500 while leaving a row
    stuck in `pending` forever — a spinner the user can never clear. `enqueue`
    marks the job `failed` with a readable reason instead.
  * **Users double-click.** Without a guard, two clicks start two full
    intelligence pipelines on the same lead: duplicate rows in every AI output
    table and twice the LLM spend. `get_or_create` returns the in-flight job.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, NotFoundError
from app.models.job import Job, JobStatus
from app.models.user import User

# A job in one of these states is still going to produce a result, so a second
# request for the same work should attach to it rather than start a rival run.
ACTIVE_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


class QueueUnavailableError(AppError):
    """Redis/Celery could not accept the task. 503, not 500 — the request was
    valid and retrying later is the right response."""

    status_code = 503
    error_code = "QUEUE_UNAVAILABLE"


async def find_active(
    db: AsyncSession, *, company_id: uuid.UUID, job_type: str, lead_id: uuid.UUID | None
) -> Job | None:
    stmt = select(Job).where(
        Job.company_id == company_id,
        Job.job_type == job_type,
        Job.lead_id == lead_id,
        Job.status.in_(ACTIVE_STATUSES),
    )
    return (await db.execute(stmt.order_by(Job.created_at.desc()))).scalars().first()


async def get_or_create(
    db: AsyncSession, *, user: User, job_type: str, lead_id: uuid.UUID | None = None
) -> tuple[Job, bool]:
    """Returns (job, created). `created` is False when an identical job is
    already in flight, so the caller can skip dispatching a duplicate task."""

    existing = await find_active(
        db, company_id=user.company_id, job_type=job_type, lead_id=lead_id
    )
    if existing is not None:
        return existing, False

    job = Job(
        company_id=user.company_id,
        job_type=job_type,
        lead_id=lead_id,
        created_by_user_id=user.id,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job, True


async def enqueue(db: AsyncSession, *, job: Job, task: Any, args: tuple) -> None:
    """Hand the job to Celery, marking it failed if the broker won't take it."""

    try:
        task.delay(*args)
    except Exception as exc:
        job.status = JobStatus.FAILED
        job.error_message = f"Could not queue task: {exc}"
        job.completed_at = datetime.now(UTC)
        await db.commit()
        raise QueueUnavailableError(
            "Background queue is unavailable, please retry shortly"
        ) from exc


async def require_job(db: AsyncSession, *, job_id: uuid.UUID, user: User) -> Job:
    """404 rather than 403 for another tenant's job — the caller must not learn
    the id exists."""

    job = await db.get(Job, job_id)
    if job is None or job.company_id != user.company_id:
        raise NotFoundError("Job not found", error_code="JOB_NOT_FOUND")
    return job


async def list_jobs(
    db: AsyncSession,
    *,
    user: User,
    lead_id: uuid.UUID | None = None,
    job_status: JobStatus | None = None,
) -> list[Job]:
    stmt = select(Job).where(Job.company_id == user.company_id)
    if lead_id is not None:
        stmt = stmt.where(Job.lead_id == lead_id)
    if job_status is not None:
        stmt = stmt.where(Job.status == job_status)
    return list((await db.execute(stmt.order_by(Job.created_at.desc()))).scalars().all())
