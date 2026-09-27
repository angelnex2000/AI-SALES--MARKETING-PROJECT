"""Crew definition — Module 4 section 6.

Two crews rather than one, because the pipeline has a human gate in the middle
and a Crew cannot wait at it:

  * `build_lead_intelligence_crew` ends at the lead score, which is what Gate 1
    (the Sales Manager assigning the lead) acts on.
  * `build_outreach_crew` picks up after assignment and ends at a draft, which
    is what Gate 2 (the Sales Executive approving the text) acts on.

The brief's single crew runs research → intelligence → outreach in one
`kickoff()`, which would produce an email for a lead no manager has assigned
to anyone — automating straight through the gate the platform is built around.
Splitting the crews is what keeps the gates real.

`Process.sequential` is deliberate. CrewAI also offers a hierarchical process
where a manager LLM decides delegation order; Module 1 settled that the order
here is fixed by data dependency, so there is nothing for it to decide and
plenty for it to get wrong.
"""

from typing import Any

from agents.crew import require_crewai
from agents.crew.agents import (
    create_campaign_agent,
    create_intelligence_agent,
    create_outreach_agent,
    create_research_agent,
)
from agents.crew.tools import build_tools

JSON_ONLY = " Respond with JSON only — no prose around it."


def build_lead_intelligence_crew(lead_context: dict[str, Any], *, verbose: bool = False) -> Any:
    """Research → buying signals → ICP → lead score. Stops at Gate 1."""

    crewai = require_crewai()
    tools = build_tools(lead_context)

    research_agent = create_research_agent(tools, verbose=verbose)
    intelligence_agent = create_intelligence_agent(tools, verbose=verbose)

    research_task = crewai.Task(
        description=(
            f"Research the lead {lead_context['lead']['name']!r} by calling "
            "research_company. Report what the tool returns." + JSON_ONLY
        ),
        expected_output="Structured research report as JSON",
        agent=research_agent,
    )
    intelligence_task = crewai.Task(
        description=(
            "Using the research report, call detect_buying_signals, score_icp_fit and "
            "score_lead in that order. Report the lead score exactly as score_lead "
            "returned it, with its confidence." + JSON_ONLY
        ),
        expected_output="Lead intelligence report as JSON",
        agent=intelligence_agent,
        context=[research_task],
    )

    return crewai.Crew(
        agents=[research_agent, intelligence_agent],
        tasks=[research_task, intelligence_task],
        process=crewai.Process.sequential,
        verbose=verbose,
    )


def build_outreach_crew(lead_context: dict[str, Any], *, verbose: bool = False) -> Any:
    """Campaign strategy → draft. Stops at Gate 2, and sends nothing."""

    crewai = require_crewai()
    tools = build_tools(lead_context)

    research_agent = create_research_agent(tools, verbose=verbose)
    campaign_agent = create_campaign_agent(tools, verbose=verbose)
    outreach_agent = create_outreach_agent(tools, verbose=verbose)

    research_task = crewai.Task(
        description=(
            f"Call research_company for {lead_context['lead']['name']!r} so the copy "
            "has verified context to work from." + JSON_ONLY
        ),
        expected_output="Structured research report as JSON",
        agent=research_agent,
    )
    campaign_task = crewai.Task(
        description="Call plan_campaign to select tone, CTA and cadence." + JSON_ONLY,
        expected_output="Campaign strategy as JSON",
        agent=campaign_agent,
        context=[research_task],
    )
    outreach_task = crewai.Task(
        description=(
            "Call draft_outreach_email. Report the subject, body, explanation and any "
            "validator findings. Do not attempt to send anything — the draft is saved "
            "for a human to approve." + JSON_ONLY
        ),
        expected_output="Email subject, body, and explanation as JSON",
        agent=outreach_agent,
        context=[research_task, campaign_task],
    )

    return crewai.Crew(
        agents=[research_agent, campaign_agent, outreach_agent],
        tasks=[research_task, campaign_task, outreach_task],
        process=crewai.Process.sequential,
        verbose=verbose,
    )


CREWS = {
    "lead_intelligence": build_lead_intelligence_crew,
    "outreach_draft": build_outreach_crew,
}


__all__ = ["CREWS", "build_lead_intelligence_crew", "build_outreach_crew"]
