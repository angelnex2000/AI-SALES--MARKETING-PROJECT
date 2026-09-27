import asyncio
import uuid
from datetime import UTC, datetime

from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.lead import Lead
from app.models.outreach import Reply
from app.services import crew_service, rag_service
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


@celery_app.task(name="tasks.run_rag_index")
def run_rag_index(job_id: str, document_id: str, company_id: str, content: str) -> None:
    """Phase 8 Module 7 — chunk, embed and store one knowledge document.

    On a worker because a long document is hundreds of chunks and hundreds of
    embedding calls. Until Phase 9 this task did not exist, so every uploaded
    document sat in `uploaded` and RAG had nothing to ground on.
    """

    asyncio.run(
        _run_rag_index(uuid.UUID(job_id), uuid.UUID(document_id), uuid.UUID(company_id), content)
    )


async def _run_rag_index(
    job_id: uuid.UUID, document_id: uuid.UUID, company_id: uuid.UUID, content: str
) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await db.commit()
        try:
            job.result = await rag_service.index_document(
                db, document_id=document_id, company_id=company_id, content=content
            )
            # `ingest` marks a document FAILED rather than leaving it in
            # `processing`; the job mirrors that so a polling UI agrees with
            # the document status it is showing beside it.
            job.status = (
                JobStatus.FAILED
                if job.result.get("status") == "failed"
                else JobStatus.COMPLETED
            )
            if job.status is JobStatus.FAILED:
                job.error_message = str(job.result.get("reason") or "indexing failed")
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface
            job.status = JobStatus.FAILED
            job.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        job.completed_at = datetime.now(UTC)
        await db.commit()


@celery_app.task(name="tasks.run_crew")
def run_crew(job_id: str, lead_id: str, crew_name: str = "lead_intelligence") -> None:
    """Phase 9 Module 4 — run a CrewAI crew over the existing agents.

    On a worker rather than inline: a crew makes several LLM round trips, and
    Module 4 section 9 asks for background jobs explicitly.
    """

    asyncio.run(_run_crew(uuid.UUID(job_id), uuid.UUID(lead_id), crew_name))


async def _run_crew(job_id: uuid.UUID, lead_id: uuid.UUID, crew_name: str) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lead = await db.get(Lead, lead_id)
        if job is None or lead is None:
            return
        await crew_service.run_crew(db, lead=lead, job=job, crew_name=crew_name)


@celery_app.task(name="tasks.run_outreach_draft")
def run_outreach_draft(
    job_id: str,
    lead_id: str,
    contact_id: str | None = None,
    campaign_goal: str | None = None,
) -> None:
    """Phase 9 Module 2 — the supervisor-planned outreach workflow.

    Research (reused if fresh) → Campaign → RAG → Outreach → EmailDraft in
    `pending_approval`. Nothing here sends anything.
    """

    asyncio.run(
        _run_outreach_draft(
            uuid.UUID(job_id),
            uuid.UUID(lead_id),
            uuid.UUID(contact_id) if contact_id else None,
            campaign_goal,
        )
    )


async def _run_outreach_draft(
    job_id: uuid.UUID,
    lead_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    campaign_goal: str | None,
) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        lead = await db.get(Lead, lead_id)
        if job is None or lead is None:
            return
        await AIOrchestrator(db).generate_outreach_draft(
            lead=lead, job=job, contact_id=contact_id, campaign_goal=campaign_goal
        )


@celery_app.task(name="tasks.run_revenue_forecast")
def run_revenue_forecast(job_id: str, period: str | None = None) -> None:
    """Module 12 — recompute the revenue forecast for a period.

    Takes no lead id: the forecast is over the tenant's whole pipeline. Also
    reached from `meeting_service.record_outcome`, since a completed meeting
    shifts win odds.
    """

    asyncio.run(_run_revenue_forecast(uuid.UUID(job_id), period))


async def _run_revenue_forecast(job_id: uuid.UUID, period: str | None) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        await AIOrchestrator(db).generate_revenue_forecast(job=job, period=period)


@celery_app.task(name="tasks.run_reply_intent")
def run_reply_intent(job_id: str, reply_id: str) -> None:
    """Module 10 — classify one inbound reply.

    Keyed to the reply rather than the lead: a lead can accumulate many
    replies, and each is a separate thing the customer said.
    """

    asyncio.run(_run_reply_intent(uuid.UUID(job_id), uuid.UUID(reply_id)))


async def _run_reply_intent(job_id: uuid.UUID, reply_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        reply = await db.get(Reply, reply_id)
        if job is None or reply is None:
            return
        await AIOrchestrator(db).classify_reply(reply=reply, job=job)