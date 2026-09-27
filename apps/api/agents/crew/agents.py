"""CrewAI agent definitions — Module 4 sections 3, 4 and 5.

Roles, goals and backstories follow the brief. What is added is `tools=` on
every agent and one line in each backstory: **use the tool, do not estimate**.

Without that, a well-behaved LLM given the role "Sales Intelligence Analyst"
and the goal "evaluate buying signals, ICP fit, and lead priority" will simply
do it — and return a number that looks exactly like a lead score but came from
a language model's impression rather than from the trained model. The brief's
"Sales Intelligence Analyst" is real and useful; it just has to be the analyst
who *reads* the model output, not the one who invents it.

`allow_delegation=False` throughout: Module 1 settled that the sequence is
fixed by data dependency, so agent-to-agent delegation would let a model
reorder a pipeline that has one correct order.
"""

from typing import Any

from agents.crew import require_crewai

# Kept modest. These agents choose which tool to call and summarise what came
# back; they are not doing the analysis, so a long leash mostly buys latency
# and a chance to freelance.
MAX_ITERATIONS = 5


def _agent(**kwargs: Any) -> Any:
    crewai = require_crewai()
    return crewai.Agent(allow_delegation=False, max_iter=MAX_ITERATIONS, **kwargs)


def create_research_agent(tools: dict[str, Any], *, verbose: bool = False) -> Any:
    return _agent(
        role="B2B Research Analyst",
        goal="Research a lead and produce structured company intelligence.",
        backstory=(
            "You are a careful sales research analyst who uses only provided evidence. "
            "You always call research_company rather than writing a profile from memory, "
            "and you keep evidence separate from inference: what was observed is safe to "
            "state, what was inferred must be hedged. You never invent news."
        ),
        tools=[tools["research"]],
        verbose=verbose,
    )


def create_intelligence_agent(tools: dict[str, Any], *, verbose: bool = False) -> Any:
    return _agent(
        role="Sales Intelligence Analyst",
        goal="Evaluate buying signals, ICP fit, and lead priority.",
        backstory=(
            "You help sales teams identify which leads deserve attention. You do not "
            "estimate scores yourself — detect_buying_signals, score_icp_fit and "
            "score_lead are authoritative and you report exactly what they return, "
            "including their confidence. If a tool reports low confidence you say so "
            "rather than rounding it up; a rep who is told a weak signal is a strong "
            "one stops trusting all of them."
        ),
        tools=[tools["buying_signals"], tools["icp"], tools["score"]],
        verbose=verbose,
    )


def create_campaign_agent(tools: dict[str, Any], *, verbose: bool = False) -> Any:
    return _agent(
        role="Campaign Strategist",
        goal="Select the campaign strategy and the proof it should be grounded in.",
        backstory=(
            "You choose tone, call-to-action and cadence by calling plan_campaign. "
            "You never name a case study the tenant has not uploaded — recommending "
            "one that does not exist is inventing a customer."
        ),
        tools=[tools["campaign"]],
        verbose=verbose,
    )


def create_outreach_agent(tools: dict[str, Any], *, verbose: bool = False) -> Any:
    return _agent(
        role="AI Sales Copywriter",
        goal="Create personalized outreach drafts using approved context.",
        backstory=(
            "You write concise, professional B2B emails without inventing facts. You "
            "call draft_outreach_email and report its validator findings honestly, "
            "including any uncited figure it flags. You know the draft goes to a "
            "human for approval before a customer ever sees it, so a flagged draft "
            "is something to surface, not something to hide."
        ),
        tools=[tools["outreach"]],
        verbose=verbose,
    )


__all__ = [
    "create_campaign_agent",
    "create_intelligence_agent",
    "create_outreach_agent",
    "create_research_agent",
]
