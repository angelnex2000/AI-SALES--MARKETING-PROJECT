import asyncio
import uuid

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.lead import Lead
from app.services.ai_orchestrator import AIOrchestrator


@celery_app.task(name="tasks.run_lead_intelligence")
def run_lead_intelligence(job_id: str, lead_id: str) -> None:
    """Celery task — replaces the FastAPI BackgroundTasks stopgap now that
    Module 9 settled on Celery + Redis for background AI jobs (real
    retries and concurrency control instead of an in-process fire-and-forget
    call)."""

    asyncio.run(_run(uuid.UUID(job_id), uuid.UUID(lead_id)))


async def _run(job_id: uuid.UUID, lead_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lead = await db.get(Lead, lead_id)
        if job is None or lead is None:
            return
        await AIOrchestrator(db).generate_lead_intelligence(lead=lead, job=job)