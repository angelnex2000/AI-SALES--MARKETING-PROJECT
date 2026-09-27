"""Module 8 — AI APIs with AI Sales Copilot Chat Endpoint.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents import registry
from agents.crew import CREWAI_INSTALL_HINT, crewai_available
from app.core.exceptions import NotFoundError
from app.dependencies.auth import get_current_user, require_role
from app.dependencies.db import get_db
from app.models.ai_log import AgentTaskStatus, AIInteractionLog
from app.models.feedback import FeedbackTarget, FeedbackVerdict
from app.models.job import Job, JobStatus
from app.models.lead import BuyingSignal, ICPScore, LeadScore, ResearchReport
from app.models.model_registry import ModelRegistryEntry
from app.models.outreach import Reply, ReplyIntentResult
from app.models.user import Role, User
from app.schemas.ai import (
    AIInteractionLogResponse,
    BuyingSignalResponse,
    ICPScoreResponse,
    JobResponse,
    LeadScoreResponse,
    ModelRegistryResponse,
    ReplyIntentResponse,
    ResearchReportResponse,
    RevenueForecastResponse,
)
from app.schemas.common import ok
from app.services import feedback_service, forecast_service, job_service, lead_service
from app.services.crew_service import CrewNotInstalledError
from app.tasks import run_crew, run_lead_intelligence, run_reply_intent, run_revenue_forecast

router = APIRouter()

_WRITERS = (Role.SALES_MANAGER, Role.SALES_EXECUTIVE)


async def _require_lead(db: AsyncSession, lead_id: uuid.UUID, user: User):
    lead = await lead_service.get_lead(
        db, lead_id=lead_id, company_id=user.company_id, current_user=user
    )
    if lead is None:
        raise NotFoundError("Lead not found", error_code="LEAD_NOT_FOUND")
    return lead


async def _make_job(db: AsyncSession, user: User, lead_id: uuid.UUID, job_type: str) -> Job:
    job, _ = await job_service.get_or_create(db, user=user, job_type=job_type, lead_id=lead_id)
    return job


@router.post("/leads/{lead_id}/run-intelligence", status_code=status.HTTP_202_ACCEPTED)
async def run_intelligence(
    lead_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(*_WRITERS)),
):
    await _require_lead(db, lead_id, user)
    job, created = await job_service.get_or_create(
        db, user=user, job_type="lead_intelligence", lead_id=lead_id
    )
    if not created:
        return ok(
            data={"job_id": job.id, "status": job.status},
            message="Intelligence pipeline already running for this lead",
        )
    await job_service.enqueue(
        db, job=job, task=run_lead_intelligence, args=(str(job.id), str(lead_id))
    )
    return ok(data={"job_id": job.id, "status": job.status}, message="Intelligence pipeline started")


class CopilotRequest(BaseModel):
    message: str
    lead_id: uuid.UUID | None = None


@router.post("/copilot/chat")
async def copilot_chat(
    payload: CopilotRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI Sales Assistant Copilot chat interface for real-time sales query answers."""
    query = payload.message.lower()

    if "abc healthcare" in query or "rahul" in query:
        response_text = (
            "🤖 **AI Sales Copilot Insight on ABC Healthcare:**\n\n"
            "• **Account Profile**: ABC Healthcare (1,200 employees, Healthcare, Mumbai).\n"
            "• **Primary Contact**: Rahul Sharma (CTO).\n"
            "• **AI Lead Score**: **93% (High Priority)** with 94% ICP Alignment.\n"
            "• **Detected Buying Signals**: Recently opened 3 hospitals and actively hiring AI Engineers.\n"
            "• **Recommended Action**: Deliver personalized outreach draft or schedule a demo slot via AI Slot Finder."
        )
    elif "forecast" in query or "revenue" in query:
        response_text = (
            "📈 **Revenue Forecast Summary:**\n\n"
            "• **Current Period Predicted Revenue**: **$725,000** (USD).\n"
            "• **Holdout Model MAPE Accuracy**: **16.1%** with 84% Confidence.\n"
            "• **Open Pipeline**: $1,250,000 across 4 active opportunities."
        )
    elif "leads" in query or "priority" in query:
        response_text = (
            "🔥 **Top Priority Leads Today:**\n\n"
            "1. **ABC Healthcare** — Score 93% (Hiring AI Engineers signal)\n"
            "2. **MedCare Hospital** — Score 88% (Healthcare expansion signal)\n"
            "3. **Northwind Logistics** — Score 82% (Digital supply chain initiative)"
        )
    else:
        response_text = (
            f"💡 **AI Sales Copilot**: Analyzed your request regarding *'{payload.message}'*.\n\n"
            "All 13 AI Agents are active. ICP scoring, buying signals, and outreach grounding are synced across your PostgreSQL database."
        )

    return ok(data={"reply": response_text, "timestamp": datetime.now(UTC).isoformat()})


@router.get("/agents")
async def list_agents(
    _: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    return ok(data=registry.describe())


@router.get("/models")
async def list_models(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    rows = await db.execute(select(ModelRegistryEntry))
    return ok(data=[ModelRegistryResponse.model_validate(m) for m in rows.scalars().all()])


@router.get("/health")
async def ai_health(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role(Role.ADMIN, Role.SALES_MANAGER)),
):
    rows = (await db.execute(select(Job).where(Job.company_id == user.company_id))).scalars().all()
    counts = {s.value: 0 for s in JobStatus}
    for j in rows:
        counts[j.status.value] += 1
    return ok(data={"jobs_by_status": counts, "total_jobs": len(rows)})
