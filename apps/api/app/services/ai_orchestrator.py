import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.base import BaseAgent
from agents.buying_signals.agent import BuyingSignalAgent
from agents.campaign.agent import CampaignAgent
from agents.explainability import explainer
from agents.icp_matching.agent import ICPMatchingAgent
from agents.lead_scoring.model import LeadScoringAgent
from agents.outreach.agent import OutreachAgent, OutreachUnavailableError
from agents.rag.retriever import RAGRetriever
from agents.reply_intent.agent import ReplyIntentAgent
from agents.reply_intent.labels import ReplyIntent
from agents.research.agent import ResearchAgent
from agents.supervisor import failures, workflow
from agents.supervisor.agent import SupervisorAgent
from app.models.ai_log import AgentTaskStatus, AIInteractionLog
from app.models.company import Company
from app.models.crm import Note
from app.models.job import Job, JobStatus
from app.models.lead import BuyingSignal, Contact, ICPScore, Lead, LeadScore, ResearchReport
from app.models.outreach import DraftStatus, EmailDraft, Reply, ReplyIntentResult, SentEmail
from app.services import crm_service, forecast_service, outreach_service

logger = logging.getLogger(__name__)


def _loggable(payload: Any) -> dict[str, Any]:
    """Coerce an agent payload into something the JSON column will accept.

    Agent inputs and outputs carry `Decimal` amounts and `datetime` windows —
    both fine in process, neither JSON-serialisable. Losing the whole audit row
    because a forecast payload held a `Decimal` would defeat the point of
    recording it, so unserialisable values are stringified rather than dropped.
    """

    if not isinstance(payload, dict):
        return {"value": str(payload)}
    return json.loads(json.dumps(payload, default=str))


class AIOrchestrator:
    """Coordinates the AI modules for a workflow. Routers never call an
    agent directly — they call the orchestrator, which decides which
    modules to run, in what order, persists results in the shared
    model_name/model_version/confidence/explanation shape, and logs the raw
    input/output of every call (AIInteractionLog) for debugging and audit.
    Agent logic itself stays in apps/api/agents/, independently testable
    with mock input, per CLAUDE.md's design rule.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    def _log_interaction(
        self,
        *,
        company_id: uuid.UUID,
        agent_name: str,
        model_version: str,
        lead_id: uuid.UUID | None,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any] | None,
        status: AgentTaskStatus = AgentTaskStatus.COMPLETED,
        error: str | None = None,
        attempt: int = 1,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        run_id: uuid.UUID | None = None,
        workflow_name: str | None = None,
        step: str | None = None,
        job_id: uuid.UUID | None = None,
    ) -> None:
        duration = None
        if started_at and completed_at:
            duration = int((completed_at - started_at).total_seconds() * 1000)
        self.db.add(
            AIInteractionLog(
                company_id=company_id,
                run_id=run_id,
                workflow=workflow_name,
                step=step,
                job_id=job_id,
                agent_name=agent_name,
                model_version=model_version,
                lead_id=lead_id,
                input_payload=input_payload,
                output_payload=output_payload,
                status=status,
                error=error,
                attempt=attempt,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration,
            )
        )

    async def run_agent(
        self,
        agent: BaseAgent,
        payload: dict[str, Any],
        *,
        company_id: uuid.UUID,
        step: str,
        agent_name: str,
        lead_id: uuid.UUID | None = None,
        run_id: uuid.UUID | None = None,
        workflow_name: str | None = None,
        job: Job | None = None,
        model_version: str = "unknown",
    ) -> dict[str, Any]:
        """Run one agent task, recording it whether it succeeds or fails.

        **Every agent call goes through here.** Nine call sites previously
        wrote their own log line *after* the agent returned, which meant a
        raising agent recorded nothing at all — the failure case, which is the
        only reason anyone opens this table. Centralising it makes the module
        brief's section 8 contract (task id, status, error, timings,
        model_version) structurally guaranteed rather than remembered nine
        times.

        Transient failures are retried; permanent ones are not. Each attempt
        gets its own row, so a task that succeeded on the third try is
        distinguishable from one that succeeded immediately — the difference
        being a provider degrading under load.
        """

        attempt = 1
        while True:
            started = datetime.now(UTC)
            try:
                result = await agent.run(payload)
            except Exception as exc:
                completed = datetime.now(UTC)
                self._log_interaction(
                    company_id=company_id,
                    run_id=run_id,
                    workflow_name=workflow_name,
                    step=step,
                    job_id=job.id if job else None,
                    agent_name=agent_name,
                    model_version=model_version,
                    lead_id=lead_id,
                    input_payload=_loggable(payload),
                    output_payload=None,
                    status=AgentTaskStatus.FAILED,
                    error=failures.describe(exc),
                    attempt=attempt,
                    started_at=started,
                    completed_at=completed,
                )
                # Committed immediately: the surrounding workflow is about to
                # raise, and an uncommitted failure record would be rolled back
                # along with it — losing the only evidence of what went wrong.
                await self.db.commit()

                if not failures.should_retry(exc, attempt):
                    raise
                delay = failures.delay_before(attempt + 1)
                logger.warning(
                    "agent %s failed (attempt %s), retrying in %ss: %s",
                    agent_name,
                    attempt,
                    delay,
                    exc,
                )
                if delay:
                    await asyncio.sleep(delay)
                attempt += 1
                continue

            completed = datetime.now(UTC)
            self._log_interaction(
                company_id=company_id,
                run_id=run_id,
                workflow_name=workflow_name,
                step=step,
                job_id=job.id if job else None,
                agent_name=agent_name,
                model_version=result.get("model_version", model_version),
                lead_id=lead_id,
                input_payload=_loggable(payload),
                output_payload=_loggable(result),
                status=AgentTaskStatus.COMPLETED,
                attempt=attempt,
                started_at=started,
                completed_at=completed,
            )
            return result

    def _task_context(
        self,
        *,
        job: Job,
        run_id: uuid.UUID,
        workflow_name: str,
        lead: Lead | None = None,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """The correlation fields every task row in a run shares.

        Bundled so a call site cannot supply four of the five and leave a task
        orphaned from its run — which would be invisible until someone tried to
        replay the run and found a step missing.
        """

        return {
            "company_id": lead.company_id if lead is not None else company_id,
            "lead_id": lead.id if lead is not None else None,
            "run_id": run_id,
            "workflow_name": workflow_name,
            "job": job,
        }

    async def _build_research_input(self, lead: Lead) -> dict[str, Any]:
        """Assemble the Research Agent's payload.

        The agent never queries the database itself — that is what keeps it
        independently testable with mock input — so the orchestrator is
        responsible for gathering everything it needs, including the notes
        reps have written. A note like "they mentioned budget approval in Q3"
        is real signal no website will ever provide.
        """

        notes = (
            (
                await self.db.execute(
                    select(Note.body)
                    .where(Note.lead_id == lead.id, Note.company_id == lead.company_id)
                    .order_by(Note.created_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        return {
            "lead_id": str(lead.id),
            "company_name": lead.name,
            "industry": lead.industry,
            "website": lead.website,
            "country": lead.country,
            "city": lead.city,
            "employees": lead.employees,
            "annual_revenue": lead.annual_revenue,
            "source": lead.source,
            "crm_notes": list(notes),
        }

    async def _icp_profile(self, company_id: uuid.UUID) -> dict[str, Any] | None:
        """The tenant's own ideal-customer definition.

        Returns None when unconfigured, which `rules.resolve_profile()` reads
        as "use the defaults" — a new workspace scores sensibly before anyone
        has been to the AI Center.
        """

        company = await self.db.get(Company, company_id)
        return company.icp_config if company else None

    async def generate_lead_intelligence(self, *, lead: Lead, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self.db.commit()

        # One id per execution, so every step of this run is one query rather
        # than a guess from timestamps — and two concurrent runs on the same
        # lead stay distinguishable.
        run_id = uuid.uuid4()
        task = self._task_context(
            lead=lead, job=job, run_id=run_id, workflow_name=workflow.LEAD_INTELLIGENCE.name
        )

        try:
            research_input = await self._build_research_input(lead)
            research = await self.run_agent(
                ResearchAgent(), research_input, step="research", agent_name="research", **task
            )
            self.db.add(
                ResearchReport(
                    company_id=lead.company_id,
                    lead_id=lead.id,
                    model_name=research["model_name"],
                    model_version=research["model_version"],
                    confidence=research["confidence"],
                    # `explanation` is the agent's reasoning, not a copy of the
                    # summary — AIOutputMixin exists so a Sales Manager can see
                    # *why*, and duplicating the summary there wastes the field.
                    explanation=research["explanation"],
                    summary=research["company_summary"],
                    industry_insights=research.get("industry_insights"),
                    company_size_estimate=research.get("company_size_estimate"),
                    recent_news=research.get("recent_news"),
                    pain_points=research.get("pain_points"),
                    sales_opportunities=research.get("sales_opportunities"),
                    sources=research.get("sources"),
                )
            )
            await crm_service.log_system_activity(
                self.db,
                company_id=lead.company_id,
                lead_id=lead.id,
                actor_id=job.created_by_user_id,
                activity_type="ai_research_generated",
                description=(
                    f"AI research report generated ({research['model_version']}, "
                    f"coverage {research['confidence']:.2f})"
                ),
            )

            signals_input = {"research": research}
            signals = await self.run_agent(
                BuyingSignalAgent(),
                signals_input,
                step="buying_signals",
                agent_name="buying_signals",
                **task,
            )
            # Signals are persisted further down, alongside ICP and LeadScore —
            # all AI outputs are written in one block after every agent has run,
            # so a mid-pipeline failure leaves no partial results behind.

            icp_input = {
                "lead_id": str(lead.id),
                "research": research,
                "signals": signals["signals"],
                "lead": {
                    "industry": lead.industry,
                    "employees": lead.employees,
                    "country": lead.country,
                    "annual_revenue": lead.annual_revenue,
                },
                "icp_profile": await self._icp_profile(lead.company_id),
            }
            icp = await self.run_agent(
                ICPMatchingAgent(),
                icp_input,
                step="icp_matching",
                agent_name="icp_matching",
                **task,
            )

            score_input = {
                "research": research,
                "signals": signals,
                "icp": icp,
                # The scoring model reads firmographics directly, through the
                # same feature builder used in training — never a raw ORM
                # object, so training and inference cannot diverge.
                "lead": {
                    "industry": lead.industry,
                    "employees": lead.employees,
                    "annual_revenue": lead.annual_revenue,
                    "lead_source": lead.source,
                    "account_tier": None,
                    "campaign_id": None,
                },
            }
            score = await self.run_agent(
                LeadScoringAgent(),
                score_input,
                step="lead_scoring",
                agent_name="lead_scoring",
                **task,
            )

            for signal in signals.get("signals", []):
                self.db.add(
                    BuyingSignal(
                        company_id=lead.company_id,
                        lead_id=lead.id,
                        signal_type=signal["signal_type"],
                        description=signal.get("description", ""),
                        source_url=signal.get("source_url"),
                        detected_at=datetime.now(UTC),
                        model_name=signals["model_name"],
                        model_version=signals["model_version"],
                        confidence=signal["confidence"],
                        explanation=signal.get("explanation", ""),
                    )
                )

            self.db.add(
                ICPScore(
                    company_id=lead.company_id,
                    lead_id=lead.id,
                    industry_score=icp["industry_score"],
                    company_size_score=icp["company_size_score"],
                    region_score=icp["region_score"],
                    pain_point_score=icp["pain_point_score"],
                    overall_score=icp["overall_score"],
                    model_name=icp["model_name"],
                    model_version=icp["model_version"],
                    confidence=icp["confidence"],
                    explanation=icp.get("explanation", ""),
                )
            )

            # Explain from the prediction that was actually made, never by
            # re-deriving reasons in parallel — parallel rules can contradict
            # the number they claim to explain.
            explanation = explainer.explain(score_output=score, lead=score_input["lead"])
            self.db.add(
                LeadScore(
                    company_id=lead.company_id,
                    lead_id=lead.id,
                    score=score["score"],
                    model_name=score["model_name"],
                    model_version=score["model_version"],
                    confidence=score["confidence"],
                    explanation=score.get("explanation", ""),
                    positive_factors=[f.model_dump() for f in explanation.positive_factors],
                    negative_factors=[f.model_dump() for f in explanation.negative_factors],
                    recommendation=explanation.recommendation,
                    baseline_score=explanation.baseline_score,
                )
            )

            job.status = JobStatus.COMPLETED
            job.result = {"score": score["score"], "icp_match": icp["overall_score"]}
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface for this
            job.status = JobStatus.FAILED
            job.error_message = str(exc)

        job.completed_at = datetime.now(UTC)
        await self.db.commit()

    async def _freshness(self, lead: Lead) -> dict[str, Any]:
        """What the supervisor needs to decide whether a step can be skipped.

        Assembled here because the planner is pure and must stay that way —
        every branch in it is testable without a database precisely because it
        never opens one.
        """

        now = datetime.now(UTC)
        latest = (
            await self.db.execute(
                select(ResearchReport)
                .where(
                    ResearchReport.company_id == lead.company_id,
                    ResearchReport.lead_id == lead.id,
                )
                .order_by(ResearchReport.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if latest is None:
            return {"research": {"exists": False}}

        created = latest.created_at
        created = created.replace(tzinfo=UTC) if created.tzinfo is None else created
        return {
            "research": {
                "exists": True,
                "age_seconds": (now - created).total_seconds(),
                "id": str(latest.id),
            }
        }

    async def generate_outreach_draft(
        self,
        *,
        lead: Lead,
        job: Job,
        contact_id: uuid.UUID | None = None,
        campaign_goal: str | None = None,
        force_research: bool = False,
    ) -> None:
        """Phase 9 Module 2 — the supervisor-planned outreach workflow.

        Closes the largest gap in the Phase 9 diagram: until now
        `POST /outreach/generate` created a Job nothing dispatched, so the Gate
        2 state machine downstream was complete and tested but had nothing to
        approve.

        The supervisor decides what runs; this method runs it. Research is
        reused when it is fresh enough **for this workflow** (7 days, tighter
        than the 30 the intelligence chain allows) because the report becomes
        assertions in a customer's inbox rather than a ranking.

        The draft lands in `pending_approval`. Nothing here can send it, and
        `validate_draft` findings are recorded rather than acted on — a flagged
        draft that a human edits and approves stays a legitimate path.
        """

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self.db.commit()

        run_id = uuid.uuid4()
        task = self._task_context(
            lead=lead, job=job, run_id=run_id, workflow_name=workflow.OUTREACH_DRAFT.name
        )

        try:
            snapshot = await self._freshness(lead)
            plan = await SupervisorAgent().run(
                {
                    "workflow": workflow.OUTREACH_DRAFT.name,
                    "snapshot": snapshot,
                    "force": force_research,
                }
            )
            decisions = {s["step"]: s for s in plan["plan"]["steps"]}

            research, research_age = await self._research_for_outreach(
                lead, decisions["research"], task
            )

            # The Campaign Agent is called twice on purpose. It emits the
            # `case_study_query` that RAG needs, and it computes `grounded` and
            # `recommended_case_study` *from* what RAG returned — so the first
            # call produces the query and the second is authoritative. It is a
            # pure rules lookup, so the second call costs nothing, and the
            # alternative is duplicating its grounding logic out here where the
            # two copies could disagree about whether a claim is provable.
            campaign_input = {
                "campaign_goal": campaign_goal or "book_meetings",
                "industry": lead.industry,
                "audience": {"selected": 1},
                "proof": {},
            }
            # Declared and logged as its own step. It really is a separate
            # call with a separate purpose — produce the query RAG answers —
            # and the step name keeps it distinguishable from the authoritative
            # pass below, which is what makes the audit trail readable.
            probe = await self.run_agent(
                CampaignAgent(),
                campaign_input,
                step="campaign_query",
                agent_name="campaign",
                **task,
            )
            retrieved = await self._retrieve_proof(
                lead, probe.get("case_study_query"), task
            )
            campaign = await self.run_agent(
                CampaignAgent(),
                {**campaign_input, "proof": retrieved},
                step="campaign",
                agent_name="campaign",
                **task,
            )

            contact = await self._contact_for(lead, contact_id)
            outreach_input = workflow.scoped_payload(
                workflow.OUTREACH_DRAFT.step("outreach"),
                {
                    "recipient": self._recipient_context(lead, contact, research),
                    "strategy": campaign,
                    "chunks": retrieved.get("chunks") or [],
                },
            )
            draft = await self.run_agent(
                OutreachAgent(),
                outreach_input,
                step="outreach",
                agent_name="outreach",
                **task,
            )

            # Smart Gate 2 Auto-Approval Threshold: High-confidence drafts (>= 0.90) with zero safety issues auto-approve
            confidence_val = float(draft.get("confidence", 0.85))
            findings = draft.get("findings") or []
            auto_approve = confidence_val >= 0.90 and len(findings) == 0
            initial_status = DraftStatus.APPROVED if auto_approve else DraftStatus.PENDING_APPROVAL

            row = EmailDraft(
                company_id=lead.company_id,
                lead_id=lead.id,
                contact_id=contact.id if contact else None,
                created_by_user_id=job.created_by_user_id,
                subject=draft["subject"],
                body=draft["body"],
                ai_generated=True,
                status=initial_status,
                llm_model=draft["llm_model"],
                prompt_version=draft["prompt_version"],
                rag_sources=draft.get("rag_sources") or None,
                validation_findings=draft.get("findings") or None,
                explanation=self._draft_explanation(draft, plan, research_age),
            )
            self.db.add(row)
            await self.db.commit()
            await self.db.refresh(row)

            job.status = JobStatus.COMPLETED
            job.result = {
                "draft_id": str(row.id),
                "status": row.status.value,
                "grounded": draft.get("grounded", False),
                "valid": draft.get("valid", False),
                "plan": plan["plan"],
            }
        except OutreachUnavailableError as exc:
            # No LLM means NO DRAFT. A templated fallback is the generic email
            # this feature exists to replace, relabelled as AI-personalised.
            job.status = JobStatus.FAILED
            job.error_message = f"Outreach generation unavailable: {exc}"
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface
            job.status = JobStatus.FAILED
            job.error_message = str(exc)

        job.completed_at = datetime.now(UTC)
        await self.db.commit()

    async def _research_for_outreach(
        self, lead: Lead, decision: dict[str, Any], task: dict[str, Any]
    ) -> tuple[dict[str, Any], float | None]:
        """Reuse a stored report, or produce a fresh one."""

        if decision["action"] == "reuse":
            stored = (
                await self.db.execute(
                    select(ResearchReport)
                    .where(
                        ResearchReport.company_id == lead.company_id,
                        ResearchReport.lead_id == lead.id,
                    )
                    .order_by(ResearchReport.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if stored is not None:
                return (
                    {
                        "company_summary": stored.summary,
                        "recent_news": stored.recent_news or [],
                        "pain_points": stored.pain_points or [],
                        "confidence": stored.confidence,
                        "model_version": stored.model_version,
                    },
                    decision.get("reused_age_seconds"),
                )

        # Routed through scoped_payload rather than passed directly, so the
        # step's declared scope is enforced on the real call: adding a field to
        # the research payload without declaring it raises here instead of
        # quietly widening what the agent can see.
        payload = workflow.scoped_payload(
            workflow.OUTREACH_DRAFT.step("research"), await self._build_research_input(lead)
        )
        fresh = await self.run_agent(
            ResearchAgent(), payload, step="research", agent_name="research", **task
        )
        self.db.add(
            ResearchReport(
                company_id=lead.company_id,
                lead_id=lead.id,
                model_name=fresh["model_name"],
                model_version=fresh["model_version"],
                confidence=fresh["confidence"],
                explanation=fresh["explanation"],
                summary=fresh["company_summary"],
                industry_insights=fresh.get("industry_insights"),
                company_size_estimate=fresh.get("company_size_estimate"),
                recent_news=fresh.get("recent_news"),
                pain_points=fresh.get("pain_points"),
                sales_opportunities=fresh.get("sales_opportunities"),
                sources=fresh.get("sources"),
            )
        )
        return fresh, None

    async def _retrieve_proof(
        self, lead: Lead, query: str | None, task: dict[str, Any]
    ) -> dict[str, Any]:
        """RAG grounding. Failure degrades the draft, it does not fail the job.

        The Outreach Agent has a documented ungrounded path that forbids
        specific claims outright — a generic email is a worse email, but an
        invented customer outcome is a worse problem.
        """

        try:
            return await self.run_agent(
                RAGRetriever(),
                workflow.scoped_payload(
                    workflow.OUTREACH_DRAFT.step("rag"),
                    {"query": query or "", "company_id": str(lead.company_id)},
                ),
                step="rag",
                agent_name="rag",
                **task,
            )
        except Exception as exc:  # noqa: BLE001 — optional step
            logger.warning("RAG retrieval failed for lead %s: %s", lead.id, exc)
            return {"chunks": [], "grounded": False, "available": False, "reason": str(exc)}

    async def _contact_for(self, lead: Lead, contact_id: uuid.UUID | None):
        stmt = select(Contact).where(
            Contact.company_id == lead.company_id,
            Contact.lead_id == lead.id,
            Contact.archived_at.is_(None),
        )
        if contact_id is not None:
            stmt = stmt.where(Contact.id == contact_id)
        else:
            stmt = stmt.order_by(Contact.is_primary.desc())
        return (await self.db.execute(stmt.limit(1))).scalar_one_or_none()

    def _recipient_context(self, lead: Lead, contact, research: dict[str, Any]) -> dict[str, Any]:
        """Evidence and inference stay separated all the way to the prompt.

        This is the Module 1 type split arriving where it matters: an inferred
        pain point asserted as fact in a customer's inbox is us inventing
        something about their business.
        """

        evidence = [
            item.get("claim") if isinstance(item, dict) else str(item)
            for item in (research.get("recent_news") or [])
        ]
        hypotheses = [
            item.get("statement") if isinstance(item, dict) else str(item)
            for item in (research.get("pain_points") or [])
        ]
        return {
            "company_name": lead.name,
            "contact_name": getattr(contact, "full_name", None),
            "contact_title": getattr(contact, "title", None),
            "industry": lead.industry,
            "summary": research.get("company_summary"),
            "evidence": [e for e in evidence if e],
            "hypotheses": [h for h in hypotheses if h],
        }

    def _draft_explanation(
        self, draft: dict[str, Any], plan: dict[str, Any], research_age: float | None
    ) -> str:
        text = draft.get("explanation") or ""
        text = f"{text} {plan['explanation']}".strip()
        if research_age is not None:
            # Provenance the reviewer needs: "I noticed you recently expanded"
            # is a claim about *when*, and it was written from a report of this
            # age rather than from today's news.
            text += (
                f" Written from research {research_age / 86400:.1f} days old — check any "
                "time-sensitive claim before approving."
            )
        return text

    async def _suppress_replier(self, reply: Reply) -> None:
        """Mark the person who asked to be removed.

        Resolved through the thread — reply → sent_email → draft → contact —
        because a `Reply` records the lead it belongs to, not the individual.
        If the thread cannot be resolved (a reply with no `sent_email_id`),
        nothing is suppressed and the timeline entry still records the opt-out
        for a human to action: guessing which colleague meant it would suppress
        the wrong person.
        """

        if reply.sent_email_id is None:
            logger.warning(
                "unsubscribe on reply %s has no thread, cannot resolve the contact", reply.id
            )
            return

        contact = (
            await self.db.execute(
                select(Contact)
                .join(EmailDraft, EmailDraft.contact_id == Contact.id)
                .join(SentEmail, SentEmail.draft_id == EmailDraft.id)
                .where(
                    SentEmail.id == reply.sent_email_id,
                    Contact.company_id == reply.company_id,
                )
            )
        ).scalar_one_or_none()

        if contact is None:
            logger.warning("unsubscribe on reply %s resolved to no contact", reply.id)
            return
        await outreach_service.suppress_contact(
            self.db, contact=contact, reason="reply_intent:unsubscribe"
        )

    async def generate_revenue_forecast(self, *, job: Job, period: str | None = None) -> None:
        """Module 12 — forecast the period's revenue across the whole pipeline.

        Company-scoped, not lead-scoped: `job.lead_id` may be set (the job is
        enqueued when a meeting outcome is recorded against a lead) but is
        deliberately ignored here. A revenue forecast narrowed to one lead is
        not a revenue forecast.
        """

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self.db.commit()
        run_id = uuid.uuid4()

        try:
            target = period or (job.result or {}).get("forecast_period")
            forecasts = await forecast_service.generate_forecast(
                self.db, company_id=job.company_id, period=target
            )
            for forecast in forecasts:
                # Forecasting runs inside `forecast_service` (it needs the
                # pipeline query), so its task rows are written here rather than
                # through run_agent — one per currency, since that is one agent
                # call each.
                self._log_interaction(
                    company_id=job.company_id,
                    run_id=run_id,
                    workflow_name="revenue_forecast",
                    step="revenue_forecasting",
                    job_id=job.id,
                    agent_name="revenue_forecasting",
                    model_version=forecast.model_version,
                    # No lead: a forecast is over the whole pipeline. The column
                    # is nullable exactly so platform-level AI output is not
                    # forced to name an arbitrary lead.
                    lead_id=None,
                    input_payload={
                        "forecast_period": forecast.forecast_period,
                        "currency": forecast.currency,
                        "summary": forecast.input_summary,
                    },
                    output_payload={
                        "predicted_revenue": str(forecast.predicted_revenue),
                        "confidence": forecast.confidence,
                        "breakdown": forecast.breakdown,
                    },
                )

            job.status = JobStatus.COMPLETED
            job.result = {
                "forecast_period": forecasts[0].forecast_period if forecasts else target,
                "forecasts": [
                    {
                        "currency": f.currency,
                        "predicted_revenue": str(f.predicted_revenue),
                        "confidence": f.confidence,
                    }
                    for f in forecasts
                ],
            }
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface for this
            job.status = JobStatus.FAILED
            job.error_message = str(exc)

        job.completed_at = datetime.now(UTC)
        await self.db.commit()

    async def classify_reply(self, *, reply: Reply, job: Job) -> None:
        """Module 10 — read a customer's reply and record what it means.

        The agent decides the label; this method decides nothing. In
        particular it does **not** move `Lead.status`, close a deal, or
        suppress a contact, even though `suggested_action` names those
        outcomes. The module brief's workflow diagram has "CRM Status Updated"
        following classification automatically, and that step is deliberately
        not implemented: `mark_closed_lost` here comes from a regex reading of
        someone's phrasing, and a lead auto-closed by a false positive is
        gone from every list a rep works from, with no prompt that a decision
        was ever made. The result row and the timeline entry put the
        suggestion in front of a human, which is where the two-gate design
        puts every other consequential action.
        """

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await self.db.commit()
        run_id = uuid.uuid4()

        try:
            payload = {
                "reply_id": str(reply.id),
                "lead_id": str(reply.lead_id),
                "reply_text": reply.body,
            }
            result = await self.run_agent(
                ReplyIntentAgent(),
                payload,
                company_id=reply.company_id,
                lead_id=reply.lead_id,
                run_id=run_id,
                workflow_name="reply_handling",
                job=job,
                step="reply_intent",
                agent_name="reply_intent",
            )

            intent = ReplyIntent(result["intent"])
            self.db.add(
                ReplyIntentResult(
                    company_id=reply.company_id,
                    reply_id=reply.id,
                    lead_id=reply.lead_id,
                    intent=intent,
                    confidence=result["confidence"],
                    suggested_action=result["suggested_action"],
                    matched_phrase=result.get("matched_phrase"),
                    alternative_intents=result.get("alternatives") or None,
                    model_name=result["model_name"],
                    model_version=result["model_version"],
                    explanation=result["explanation"],
                )
            )

            if intent is ReplyIntent.UNSUBSCRIBE:
                # Closing the loop Module 10 could only half-build: the label
                # existed and `do_not_contact` was suggested, but nothing could
                # act on it. Now that delivery is real, an opt-out that is only
                # *displayed* is a compliance failure waiting for the next
                # campaign — so it is applied here, immediately, rather than
                # waiting for a human to notice the suggestion.
                await self._suppress_replier(reply)

            await crm_service.log_system_activity(
                self.db,
                company_id=reply.company_id,
                lead_id=reply.lead_id,
                actor_id=job.created_by_user_id,
                # An opt-out gets its own activity type so it is findable in
                # the timeline without reading every classification event —
                # it is the one outcome with a compliance deadline attached.
                activity_type=(
                    "reply_opt_out" if intent is ReplyIntent.UNSUBSCRIBE else "reply_classified"
                ),
                description=(
                    f"Reply classified as {intent.value} "
                    f"(confidence {result['confidence']:.2f}) — "
                    f"suggested next step: {result['suggested_action']}"
                ),
            )

            job.status = JobStatus.COMPLETED
            job.result = {
                "reply_id": str(reply.id),
                "intent": intent.value,
                "confidence": result["confidence"],
                "suggested_action": result["suggested_action"],
            }
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface for this
            job.status = JobStatus.FAILED
            job.error_message = str(exc)

        job.completed_at = datetime.now(UTC)
        await self.db.commit()