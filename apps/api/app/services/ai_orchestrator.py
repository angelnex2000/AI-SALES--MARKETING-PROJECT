import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agents.buying_signals.agent import BuyingSignalAgent
from agents.icp_matching.agent import ICPMatchingAgent
from agents.lead_scoring.model import LeadScoringAgent
from agents.research.agent import ResearchAgent
from app.models.ai_log import AIInteractionLog
from app.models.job import Job, JobStatus
from app.models.lead import BuyingSignal, ICPScore, Lead, LeadScore, ResearchReport


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
        lead_id: uuid.UUID,
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
    ) -> None:
        self.db.add(
            AIInteractionLog(
                company_id=company_id,
                agent_name=agent_name,
                model_version=model_version,
                lead_id=lead_id,
                input_payload=input_payload,
                output_payload=output_payload,
            )
        )

    async def generate_lead_intelligence(self, *, lead: Lead, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        await self.db.commit()

        try:
            research_input = {"lead_id": str(lead.id), "name": lead.name}
            research = await ResearchAgent().run(research_input)
            self._log_interaction(
                company_id=lead.company_id,
                agent_name="research",
                model_version=research["model_version"],
                lead_id=lead.id,
                input_payload=research_input,
                output_payload=research,
            )
            self.db.add(
                ResearchReport(
                    company_id=lead.company_id,
                    lead_id=lead.id,
                    model_name=research["model_name"],
                    model_version=research["model_version"],
                    confidence=research["confidence"],
                    explanation=research.get("summary", ""),
                    summary=research.get("summary", ""),
                    industry_insights=research.get("industry_insights"),
                    company_size_estimate=research.get("company_size_estimate"),
                    recent_news=research.get("recent_news"),
                    pain_points=research.get("pain_points"),
                    sources=research.get("sources"),
                )
            )

            signals_input = {"research": research}
            signals = await BuyingSignalAgent().run(signals_input)
            self._log_interaction(
                company_id=lead.company_id,
                agent_name="buying_signals",
                model_version=signals["model_version"],
                lead_id=lead.id,
                input_payload=signals_input,
                output_payload=signals,
            )

            icp_input = {"lead_id": str(lead.id), "research": research}
            icp = await ICPMatchingAgent().run(icp_input)
            self._log_interaction(
                company_id=lead.company_id,
                agent_name="icp_matching",
                model_version=icp["model_version"],
                lead_id=lead.id,
                input_payload=icp_input,
                output_payload=icp,
            )

            score_input = {"research": research, "signals": signals, "icp": icp}
            score = await LeadScoringAgent().run(score_input)
            self._log_interaction(
                company_id=lead.company_id,
                agent_name="lead_scoring",
                model_version=score["model_version"],
                lead_id=lead.id,
                input_payload=score_input,
                output_payload=score,
            )

            for signal in signals.get("signals", []):
                self.db.add(
                    BuyingSignal(
                        company_id=lead.company_id,
                        lead_id=lead.id,
                        signal_type=signal["signal_type"],
                        description=signal.get("description", ""),
                        source_url=signal.get("source_url"),
                        detected_at=signal.get("detected_at", datetime.now(timezone.utc)),
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

            self.db.add(
                LeadScore(
                    company_id=lead.company_id,
                    lead_id=lead.id,
                    score=score["score"],
                    model_name=score["model_name"],
                    model_version=score["model_version"],
                    confidence=score["confidence"],
                    explanation=score.get("explanation", ""),
                )
            )

            job.status = JobStatus.COMPLETED
            job.result = {"score": score["score"], "icp_match": icp["overall_score"]}
        except Exception as exc:  # noqa: BLE001 — job.error_message is the intended surface for this
            job.status = JobStatus.FAILED
            job.error_message = str(exc)

        job.completed_at = datetime.now(timezone.utc)
        await self.db.commit()