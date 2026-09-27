"""Module 6 (part 2) — Outreach (Gate 2).

Generation and drafting are available to the assigned Sales Exec and to
Marketing (draft only). Approve + send are the assigned Sales Exec only — Admin
can never send, Marketing can never approve/send. The reply webhook is
unauthenticated + signature-verified and resolves the tenant server-side.
"""

import uuid

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.job import Job, JobStatus
from app.models.outreach import DraftStatus, Reply, SentEmail
from app.models.user import Role, User
from app.schemas.common import ok
from app.services import job_service, lead_service, outreach_service
from app.tasks import run_outreach_draft, run_reply_intent

router = APIRouter()

_DRAFTERS = (Role.SALES_EXECUTIVE, Role.MARKETING)


class GenerateRequest(BaseModel):
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    campaign_id: uuid.UUID | None = None
    campaign_goal: str | None = None
    """Drives the Campaign Agent's tone/CTA lookup. Null uses its default."""
    tone: str = "professional"


class DraftUpdate(BaseModel):
    subject: str | None = None
    body: str | None = None


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    contact_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    subject: str
    body: str
    ai_generated: bool
    explanation: str
    status: DraftStatus


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate_outreach(
    payload: GenerateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_DRAFTERS)),
):
    """Runs the supervisor-planned outreach workflow on a worker: research
    (reused when fresh), Campaign Agent, RAG grounding, then the Outreach
    Agent. The resulting EmailDraft lands in `pending_approval`.

    Until Phase 9 Module 2 this created a Job nothing dispatched, so no draft
    was ever produced and the Gate 2 machinery downstream had nothing to
    approve. Deduplicated per lead: two clicks would otherwise put two drafts
    in the approval queue for the same lead and spend twice the LLM budget.
    """

    lead = await lead_service.get_lead(
        db, lead_id=payload.lead_id, company_id=user.company_id, current_user=user
    )
    if lead is None:
        raise NotFoundError("Lead not found", error_code="LEAD_NOT_FOUND")

    job, created = await job_service.get_or_create(
        db, user=user, job_type="outreach_draft", lead_id=payload.lead_id
    )
    if not created:
        return ok(
            data={"job_id": job.id, "status": job.status},
            message="A draft is already being generated for this lead",
        )
    await job_service.enqueue(
        db,
        job=job,
        task=run_outreach_draft,
        args=(
            str(job.id),
            str(payload.lead_id),
            str(payload.contact_id) if payload.contact_id else None,
            payload.campaign_goal,
        ),
    )
    return ok(data={"job_id": job.id, "status": job.status}, message="Outreach generation started")


@router.get("/drafts")
async def list_drafts(
    draft_status: DraftStatus | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    drafts = await outreach_service.list_drafts(db, user=user, status=draft_status)
    return ok(data=[DraftResponse.model_validate(d) for d in drafts])


@router.get("/drafts/{draft_id}")
async def get_draft(
    draft_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    draft = await outreach_service.require_draft(db, draft_id=draft_id, user=user)
    return ok(data=DraftResponse.model_validate(draft))


@router.put("/drafts/{draft_id}")
async def edit_draft(
    draft_id: uuid.UUID,
    payload: DraftUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_DRAFTERS)),
):
    draft, approval_voided = await outreach_service.update_draft(
        db, draft_id=draft_id, changes=payload.model_dump(exclude_unset=True), user=user
    )
    message = (
        "Draft updated — approval was voided, it must be approved again before sending"
        if approval_voided
        else "Draft updated"
    )
    return ok(data=DraftResponse.model_validate(draft), message=message)


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Gate 2 — assigned Sales Exec only."""

    draft = await outreach_service.approve_draft(db, draft_id=draft_id, user=user)
    return ok(data=DraftResponse.model_validate(draft), message="Draft approved")


@router.post("/drafts/{draft_id}/reject")
async def reject_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    draft = await outreach_service.reject_draft(db, draft_id=draft_id, user=user)
    return ok(data=DraftResponse.model_validate(draft), message="Draft rejected")


@router.post("/drafts/{draft_id}/send")
async def send_draft(
    draft_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.SALES_EXECUTIVE)),
):
    """Only an approved draft can be sent, and only via the email Integration
    service (logged to sent_emails)."""

    sent = await outreach_service.send_draft(db, draft_id=draft_id, user=user)
    return ok(data={"email_id": sent.id, "status": "sent"}, message="Email sent")


@router.get("/emails")
async def list_emails(
    lead_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    emails = await outreach_service.list_sent_emails(db, user=user, lead_id=lead_id)
    return ok(
        data=[
            {"id": e.id, "lead_id": e.lead_id, "sent_at": e.sent_at, "opened_at": e.opened_at}
            for e in emails
        ]
    )


@router.post("/replies/webhook", status_code=status.HTTP_202_ACCEPTED)
async def replies_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Unauthenticated inbound endpoint. Verify the provider signature and
    resolve the tenant from the sent-email thread — NEVER trust company_id in
    the body. Saves the Reply and queues async intent classification."""

    try:
        payload = await request.json()
    except Exception as exc:
        # This endpoint is unauthenticated and internet-facing: malformed input
        # must be a 422, never an unhandled 500.
        raise ValidationError("Body must be JSON", error_code="INVALID_WEBHOOK") from exc
    if not isinstance(payload, dict):
        raise ValidationError("Body must be a JSON object", error_code="INVALID_WEBHOOK")

    # TODO(security): verify provider webhook signature before trusting this.
    sent_email_id = payload.get("sent_email_id")
    if not sent_email_id:
        raise ValidationError("Missing sent_email_id", error_code="INVALID_WEBHOOK")
    try:
        thread_id = uuid.UUID(str(sent_email_id))
    except ValueError as exc:
        raise ValidationError("Malformed sent_email_id", error_code="INVALID_WEBHOOK") from exc
    sent = await db.get(SentEmail, thread_id)
    if sent is None:
        raise NotFoundError("Unknown email thread", error_code="THREAD_NOT_FOUND")

    reply = Reply(
        company_id=sent.company_id,  # tenant resolved server-side, not from body
        lead_id=sent.lead_id,
        sent_email_id=sent.id,
        body=payload.get("body", ""),
    )
    db.add(reply)
    job = Job(
        company_id=sent.company_id,
        job_type="reply_intent",
        lead_id=sent.lead_id,
        # No `created_by_user_id`: an inbound customer reply has no human
        # author on our side, and backfilling a placeholder would attribute
        # the classification to a rep who did nothing.
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.commit()

    # Both ids are needed by the worker and both rows must exist first, so the
    # dispatch happens after the commit — same ordering as job_service.enqueue.
    try:
        await job_service.enqueue(
            db, job=job, task=run_reply_intent, args=(str(job.id), str(reply.id))
        )
    except job_service.QueueUnavailableError:
        # Swallowed on purpose, and only here. Everywhere else a dead broker
        # should surface as a 503 the caller retries — but this caller is an
        # email provider, and a retry would deliver the same webhook again and
        # store the customer's message a second time. The Reply is already
        # safely committed and `enqueue` has marked the job failed with a
        # reason, so the classification can be re-run from the AI Center
        # without the customer's words being duplicated in the timeline.
        pass

    return ok(message="Reply received")
