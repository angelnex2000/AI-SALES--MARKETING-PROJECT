"""CrewAI workflow integration — Module 4 sections 7 and 8.

The brief's `SupervisorWorkflow.run_lead_workflow` calls `crew.kickoff()`
inline and the endpoint returns the result directly. This does the same job
while keeping the five things section 9 says production still needs, all of
which already exist here:

  * **Background jobs** — dispatched to Celery, 202 + job_id, never inline. A
    Crew makes several LLM round trips; inline it would hold a request open for
    a minute and time out behind any proxy.
  * **Stored task results** — every underlying agent call still goes through
    `AIOrchestrator.run_agent`, so it lands in `ai_interaction_logs` with
    status, error and timings whether it works or not.
  * **Validated JSON** — the tools return validated agent output; the Crew's
    own prose is stored as a summary, never parsed into business data.
  * **Retries** — inherited from `run_agent`'s transient-failure policy.
  * **Human approval** — the outreach crew stops at a `pending_approval` draft.
    Nothing here can send.

**The Crew's narration is never the source of truth.** `kickoff()` returns
whatever the last agent said, and an LLM asked to "report the lead score
exactly" will occasionally round it, reformat it, or summarise two numbers into
one. So the persisted values are read from the *tools'* recorded state, and the
Crew's text is kept alongside as commentary. That is the whole reason
`build_tools` returns its `state` dict.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.crew import CrewUnavailableError, crewai_available
from app.core.exceptions import AppError
from app.models.company import Company
from app.models.crm import Note
from app.models.job import Job, JobStatus
from app.models.lead import Contact, Lead


class CrewNotInstalledError(AppError):
    """503, not 500: the request was valid, the optional dependency is absent."""

    status_code = 503
    error_code = "CREWAI_NOT_INSTALLED"


async def build_lead_context(db: AsyncSession, lead: Lead) -> dict[str, Any]:
    """Everything the crew's tools may see, for exactly one lead.

    Assembled here because the tools — like every agent in this codebase —
    never query the database. Binding it per run is also the tenant boundary:
    there is no lead-id argument for a model to pass incorrectly.
    """

    notes = (
        (
            await db.execute(
                select(Note.body)
                .where(Note.lead_id == lead.id, Note.company_id == lead.company_id)
                .order_by(Note.created_at.desc())
                .limit(10)
            )
        )
        .scalars()
        .all()
    )
    company = await db.get(Company, lead.company_id)
    contact = (
        await db.execute(
            select(Contact)
            .where(
                Contact.company_id == lead.company_id,
                Contact.lead_id == lead.id,
                Contact.archived_at.is_(None),
            )
            .order_by(Contact.is_primary.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    lead_fields = {
        "name": lead.name,
        "industry": lead.industry,
        "website": lead.website,
        "country": lead.country,
        "city": lead.city,
        "employees": lead.employees,
        "annual_revenue": lead.annual_revenue,
        "source": lead.source,
    }
    return {
        "lead_id": str(lead.id),
        "company_id": str(lead.company_id),
        "lead": lead_fields,
        "research_input": {"lead_id": str(lead.id), "company_name": lead.name, **lead_fields, "crm_notes": list(notes)},
        "scoring_features": {
            "industry": lead.industry,
            "employees": lead.employees,
            "annual_revenue": lead.annual_revenue,
            "lead_source": lead.source,
            "account_tier": None,
            "campaign_id": None,
        },
        "icp_profile": company.icp_config if company else None,
        "recipient": {
            "company_name": lead.name,
            "contact_name": getattr(contact, "full_name", None),
            "contact_title": getattr(contact, "title", None),
            "industry": lead.industry,
        },
        "contact_id": str(contact.id) if contact else None,
    }


async def run_crew(
    db: AsyncSession, *, lead: Lead, job: Job, crew_name: str = "lead_intelligence"
) -> None:
    """Execute a crew and record what it produced.

    `kickoff()` is synchronous and blocking, and the tools inside it open their
    own event loops — so it runs in a worker thread. Calling it directly from
    this coroutine would block the worker's loop for the whole crew and then
    fail the moment a tool tried `asyncio.run` inside an already-running loop.
    """

    job.status = JobStatus.RUNNING
    job.started_at = datetime.now(UTC)
    await db.commit()

    try:
        if not crewai_available():
            raise CrewUnavailableError(
                "crewai is not importable in this environment — see requirements-crewai.txt"
            )

        from agents.crew.crew import CREWS
        from agents.crew.tools import build_tools

        if crew_name not in CREWS:
            raise ValueError(f"unknown crew {crew_name!r}; known: {sorted(CREWS)}")

        context = await build_lead_context(db, lead)
        tools = build_tools(context)
        crew = CREWS[crew_name](context)

        narration = await asyncio.to_thread(crew.kickoff)

        # Business values come from the tools' recorded state, never from the
        # Crew's narration — see the module docstring.
        state = tools["state"]
        job.status = JobStatus.COMPLETED
        job.result = {
            "crew": crew_name,
            "run_id": str(uuid.uuid4()),
            "lead_score": (state.get("score") or {}).get("score"),
            "icp_overall": (state.get("icp") or {}).get("overall_score"),
            "signal_count": len((state.get("signals") or {}).get("signals", [])),
            "draft_subject": (state.get("draft") or {}).get("subject"),
            "steps_completed": sorted(state),
            "narration": str(narration)[:4000],
        }
    except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface
        job.status = JobStatus.FAILED
        job.error_message = f"{type(exc).__name__}: {exc}"[:2000]

    job.completed_at = datetime.now(UTC)
    await db.commit()


__all__ = ["CrewNotInstalledError", "build_lead_context", "run_crew"]
