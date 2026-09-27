"""CrewAI tools that call this platform's real agents.

Module 4 section 9 lists what a production version still needs — background
jobs, stored task results, validated JSON, retries, human approval — and every
one of those already exists on the `AIOrchestrator` path. This module is how the
Crew reaches them instead of reimplementing them inside a prompt.

The difference matters most for two of the tools:

  * `score_lead` returns the trained model's number. The brief's skeleton has a
    "Sales Intelligence Analyst" persona *produce* the lead intelligence report
    from a prompt, which would replace a model measured at ROC-AUC 0.62 with a
    language model's impression of one — and the score is what a rep
    prioritises their day by.
  * `draft_outreach` runs `validator.validate_draft` and returns its findings.
    A persona writing an email directly would skip the uncited-figure check,
    which is the one that catches "we reduced hospital support cost by 80%"
    when nobody measured it.

Tools are built by a factory rather than declared at module level because
`crewai.tools.BaseTool` has to be imported to subclass it, and this module must
stay importable in an environment without CrewAI.

**Async bridging.** The platform's agents are `async`; CrewAI tools are called
synchronously from `Crew.kickoff()`. `crew_service` runs `kickoff()` in a worker
thread, so each tool can open its own event loop with `asyncio.run` — safe
there, and an error inside a thread that already had a running loop.
"""

import asyncio
import json
from typing import Any

from agents.buying_signals.agent import BuyingSignalAgent
from agents.campaign.agent import CampaignAgent
from agents.crew import require_crewai
from agents.icp_matching.agent import ICPMatchingAgent
from agents.lead_scoring.model import LeadScoringAgent
from agents.outreach.agent import OutreachAgent
from agents.research.agent import ResearchAgent


def _run(coro) -> Any:
    """Execute an async agent from a synchronous CrewAI tool call."""

    return asyncio.run(coro)


def _json(payload: Any) -> str:
    """CrewAI tools return strings; the contract is that they return JSON.

    Section 5 of Module 3 — agents exchange structured data, not paragraphs —
    survives the trip through CrewAI only if every tool serialises rather than
    narrating.
    """

    return json.dumps(payload, default=str)


def build_tools(context: dict[str, Any]) -> dict[str, Any]:
    """Tools bound to one lead's context.

    `context` is assembled by `crew_service` from the database, so the tools —
    like the agents behind them — never query anything themselves. Binding it
    per crew run is also what keeps a tool from being able to reach a different
    tenant's lead: there is no lead id parameter for a model to get wrong.
    """

    crewai = require_crewai()
    from crewai.tools import BaseTool  # noqa: PLC0415 — see module docstring

    state: dict[str, Any] = {}

    class ResearchTool(BaseTool):
        name: str = "research_company"
        description: str = (
            "Produce a structured research report for the lead under discussion. "
            "Returns JSON with company_summary, recent_news (evidence), pain_points "
            "(inference), sources and a coverage confidence. Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            state["research"] = _run(ResearchAgent().run(context["research_input"]))
            return _json(state["research"])

    class BuyingSignalTool(BaseTool):
        name: str = "detect_buying_signals"
        description: str = (
            "Detect timing signals from the research report's evidenced news only. "
            "Call research_company first. Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            research = state.get("research")
            if research is None:
                return _json({"error": "call research_company first"})
            state["signals"] = _run(BuyingSignalAgent().run({"research": research}))
            return _json(state["signals"])

    class ICPTool(BaseTool):
        name: str = "score_icp_fit"
        description: str = (
            "Score the lead against this tenant's own ideal-customer profile. "
            "Call research_company and detect_buying_signals first. Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            research = state.get("research")
            if research is None:
                return _json({"error": "call research_company first"})
            state["icp"] = _run(
                ICPMatchingAgent().run(
                    {
                        "lead_id": context["lead_id"],
                        "research": research,
                        "signals": (state.get("signals") or {}).get("signals", []),
                        "lead": context["lead"],
                        "icp_profile": context.get("icp_profile"),
                    }
                )
            )
            return _json(state["icp"])

    class LeadScoreTool(BaseTool):
        name: str = "score_lead"
        description: str = (
            "Return the trained lead score (0-100) with its component breakdown and "
            "the model's measured confidence. This is the authoritative score — do "
            "not estimate one yourself. Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            state["score"] = _run(
                LeadScoringAgent().run(
                    {
                        "research": state.get("research") or {},
                        "signals": state.get("signals") or {},
                        "icp": state.get("icp") or {},
                        "lead": context["scoring_features"],
                    }
                )
            )
            return _json(state["score"])

    class CampaignTool(BaseTool):
        name: str = "plan_campaign"
        description: str = (
            "Look up the campaign strategy (tone, CTA, cadence) for this lead's "
            "industry and return it with a case-study query for retrieval. "
            "Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            state["campaign"] = _run(
                CampaignAgent().run(
                    {
                        "campaign_goal": context.get("campaign_goal") or "book_meetings",
                        "industry": context["lead"].get("industry"),
                        "audience": {"selected": 1},
                        "proof": context.get("proof") or {},
                    }
                )
            )
            return _json(state["campaign"])

    class OutreachTool(BaseTool):
        name: str = "draft_outreach_email"
        description: str = (
            "Write the outreach email using the research and campaign strategy, "
            "grounded in retrieved proof. Returns the draft plus validator findings. "
            "The draft is NOT sent — it is saved for human approval. Takes no arguments."
        )

        def _run(self, *args, **kwargs) -> str:
            research = state.get("research") or {}
            state["draft"] = _run(
                OutreachAgent().run(
                    {
                        "recipient": {
                            **context["recipient"],
                            "summary": research.get("company_summary"),
                            "evidence": [
                                item.get("claim") if isinstance(item, dict) else str(item)
                                for item in (research.get("recent_news") or [])
                            ],
                            "hypotheses": [
                                item.get("statement") if isinstance(item, dict) else str(item)
                                for item in (research.get("pain_points") or [])
                            ],
                        },
                        "strategy": state.get("campaign") or {},
                        "chunks": context.get("chunks") or [],
                    }
                )
            )
            return _json(state["draft"])

    return {
        "crewai": crewai,
        "state": state,
        "research": ResearchTool(),
        "buying_signals": BuyingSignalTool(),
        "icp": ICPTool(),
        "score": LeadScoreTool(),
        "campaign": CampaignTool(),
        "outreach": OutreachTool(),
    }


__all__ = ["build_tools"]
