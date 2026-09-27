"""The agent capability map — Phase 9 Module 1.

Thirteen agents exist under `agents/`. Until now the only place their
relationships were written down was prose in CLAUDE.md and the shape of
`AIOrchestrator`'s method bodies, which means the architecture could drift from
the code without anything failing. This module makes it data, and
`tests/test_agent_registry.py` holds it to the code: every entry point must
import, every declared `invoked_by` must resolve, and the declared workflow
must match the agent sequence the orchestrator actually logs.

**A registry that is allowed to lie is worse than no registry**, because it
gets read as documentation. So `invoked_by=None` is a first-class, tested
state: it records an agent that is built and tested but that no code path in
`app/` can reach. Three were in that state when this file was written —
campaign, outreach and embeddings — and each was wired in a later module. The
set is now empty and pinned empty by test, so an agent that becomes
unreachable fails CI rather than quietly becoming decoration in the AI Center.

## Why the supervisor is a deterministic executor, not a reasoning loop

Phase 9 Module 2 introduces CrewAI concepts, whose default posture is an LLM
supervisor choosing which agent to delegate to. That is the wrong shape here
and this file is where the reason lives:

  * The order is **fixed by data dependency**, not by judgement. Buying Signals
    reads `research.recent_news`; ICP reads the signals; Lead Scoring reads all
    three. There is nothing to decide — a model asked to choose would be
    picking between one valid order and several broken ones.
  * The output is a **lead score a rep prioritises work by**. A nondeterministic
    sequence means the same lead scores differently on re-run with nothing
    changed, and `AIInteractionLog` stops being a reproduction of what happened.
  * Failures must be reproducible. A hardcoded graph fails the same way twice.

So `determinism` is recorded per agent, and exactly one agent in the system is
`llm` — the Outreach Agent, whose output is the one thing a human approves
before it reaches a customer. That is not a coincidence: it is the design.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentSpec:
    """One agent's contract, as declared rather than as remembered."""

    name: str
    role: str
    """One sentence. If an agent needs two, it is doing two jobs."""
    module: str
    entry_class: str
    consumes: tuple[str, ...]
    """What it needs in its payload. Agents never query the database — the
    caller assembles this, which is what keeps them testable from a mock."""
    produces: tuple[str, ...]
    """Tables the orchestrating service writes from its output. Empty when the
    output is returned live rather than persisted."""
    determinism: str
    """`rules` | `model` | `llm`. Anything but `rules` re-runs to a different
    answer and needs its version pinned in the output row."""
    invoked_by: str | None
    """Dotted path of the service function that runs it, or None when nothing
    in `app/` reaches it. Verified by test — this field cannot rot quietly."""
    human_gate: str | None = None
    """Which approval gate its output passes through before affecting a
    customer. None means the output is internal."""
    notes: str = ""


# `rules` agents are deterministic; `model` agents load a trained artifact and
# fall back to a documented heuristic when it is absent; `llm` calls a provider.
# `live` is deterministic logic over data that changes underneath it — the same
# lead researched twice returns different news because the world moved, not
# because the agent is stochastic. Worth its own label: someone debugging why
# two reports differ needs to know which kind of variance they are looking at.
RULES = "rules"
MODEL = "model"
LLM = "llm"
LIVE = "live"

GATE_1 = "gate_1_manager_assigns"
GATE_2 = "gate_2_exec_approves_send"


AGENTS: tuple[AgentSpec, ...] = (
    AgentSpec(
        name="supervisor",
        role="Plan which workflow steps must run and which can reuse stored output.",
        module="agents.supervisor.agent",
        entry_class="SupervisorAgent",
        consumes=("workflow name", "freshness snapshot"),
        produces=(),
        determinism=RULES,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_outreach_draft",
        notes=(
            "Plans only — no database handle, imports no other agent, returns a plan rather "
            "than a result. AIOrchestrator executes it."
        ),
    ),
    AgentSpec(
        name="research",
        role="Build a company profile from firmographics, CRM notes and evidenced news.",
        module="agents.research.agent",
        entry_class="ResearchAgent",
        consumes=("lead firmographics", "crm_notes", "web search results"),
        produces=("ai_research_reports",),
        determinism=LIVE,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_lead_intelligence",
        notes=(
            "Evidence and inference are separate types so downstream cannot render a guess as a "
            "fact. Live web sourcing (TinyFish search + fetch) supplies recent_news; with no key "
            "it degrades to lead data and CRM notes and reports model_version "
            "'research-rules-v1' instead of 'research-web-v1'."
        ),
    ),
    AgentSpec(
        name="buying_signals",
        role="Detect timing signals from evidenced news only.",
        module="agents.buying_signals.agent",
        entry_class="BuyingSignalAgent",
        consumes=("research.recent_news", "research.confidence"),
        produces=("buying_signals",),
        determinism=RULES,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_lead_intelligence",
        notes="Never reads pain_points — that would launder an inferred industry fact into a signal.",
    ),
    AgentSpec(
        name="icp_matching",
        role="Score a lead against the tenant's own ideal-customer profile.",
        module="agents.icp_matching.agent",
        entry_class="ICPMatchingAgent",
        consumes=("research", "buying_signals", "lead firmographics", "Company.icp_config"),
        produces=("icp_scores",),
        determinism=RULES,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_lead_intelligence",
    ),
    AgentSpec(
        name="lead_scoring",
        role="Rank a cold lead 0-100 for who to call first.",
        module="agents.lead_scoring.model",
        entry_class="LeadScoringAgent",
        consumes=("research", "buying_signals", "icp", "lead firmographics"),
        produces=("lead_scores",),
        determinism=MODEL,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_lead_intelligence",
        human_gate=GATE_1,
        notes="Feeds the Sales Manager's assignment decision; ROC-AUC 0.62, lift 1.48x top decile.",
    ),
    AgentSpec(
        name="embeddings",
        role="Embed knowledge-base chunks for RAG retrieval.",
        module="agents.embeddings.agent",
        entry_class="EmbeddingsAgent",
        consumes=("knowledge chunk text",),
        produces=("knowledge_embeddings",),
        determinism=MODEL,
        invoked_by="app.services.rag_service.index_document",
        notes=(
            "Reached through agents/rag/ingest.py, which owns the document status "
            "transitions — a failure sets FAILED explicitly rather than leaving a document "
            "in `processing`, where RAG search excludes it with nothing explaining why."
        ),
    ),
    AgentSpec(
        name="campaign",
        role="Plan campaign strategy and emit a case-study query for RAG to answer.",
        module="agents.campaign.agent",
        entry_class="CampaignAgent",
        consumes=("campaign_goal", "industry", "audience stats", "rag proof"),
        produces=(),
        determinism=RULES,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_outreach_draft",
        notes=(
            "Called twice per draft on purpose: once to obtain the case_study_query RAG needs, "
            "then again with the retrieved proof, which is what computes `grounded`. It is a "
            "pure rules lookup, so the second call is free and the grounding logic stays in "
            "one place."
        ),
    ),
    AgentSpec(
        name="outreach",
        role="Write a personalised, RAG-grounded email draft.",
        module="agents.outreach.agent",
        entry_class="OutreachAgent",
        consumes=("recipient context", "campaign strategy", "rag chunks"),
        produces=("email_drafts",),
        determinism=LLM,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_outreach_draft",
        human_gate=GATE_2,
        notes=(
            "The only LLM agent in the system, and the only one whose output a human approves "
            "before a customer sees it. No key means the job fails — a templated fallback is "
            "the generic email this feature replaces."
        ),
    ),
    AgentSpec(
        name="rag",
        role="Retrieve grounding chunks from the tenant's own approved documents.",
        module="agents.rag.retriever",
        entry_class="RAGRetriever",
        consumes=("case_study_query", "company_id"),
        produces=("rag_retrieval_logs",),
        determinism=MODEL,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.generate_outreach_draft",
        notes=(
            "Also reachable via POST /rag/search. The pgvector similarity query is still a "
            "TODO, so it currently returns no chunks with `available=True` — 'we looked and "
            "found nothing', which correctly routes "
            "outreach to its ungrounded prompt. `available=False` is reserved for 'we could "
            "not look'; conflating the two silently downgrades a grounded email."
        ),
    ),
    AgentSpec(
        name="reply_intent",
        role="Classify what a customer's reply means and what to do next.",
        module="agents.reply_intent.agent",
        entry_class="ReplyIntentAgent",
        consumes=("reply body",),
        produces=("reply_intent_results",),
        determinism=RULES,
        invoked_by="app.services.ai_orchestrator.AIOrchestrator.classify_reply",
        notes="suggested_action is a suggestion; nothing downstream executes it.",
    ),
    AgentSpec(
        name="meeting_scheduler",
        role="Propose bookable slots from working hours minus existing meetings.",
        module="agents.meeting_scheduler.agent",
        entry_class="MeetingSchedulerAgent",
        consumes=("Company.scheduling_config", "owner busy windows", "preferred_days"),
        produces=(),
        determinism=RULES,
        invoked_by="app.services.meeting_service.suggest_slots",
        notes="Returns proposals only; POST /meetings books, and re-checks for clashes.",
    ),
    AgentSpec(
        name="revenue_forecasting",
        role="Forecast a period's revenue from the weighted pipeline.",
        module="agents.forecasting.model",
        entry_class="RevenueForecastingAgent",
        consumes=("open deals", "committed revenue", "won-revenue history"),
        produces=("revenue_forecasts",),
        determinism=MODEL,
        invoked_by="app.services.forecast_service.generate_forecast",
    ),
    AgentSpec(
        name="feedback_learning",
        role="Report measurable AI quality and whether retraining is worth evaluating.",
        module="agents.feedback_learning.agent",
        entry_class="FeedbackLearningAgent",
        consumes=("draft outcomes", "edit distances", "forecast errors", "human ratings"),
        produces=(),
        determinism=RULES,
        invoked_by="app.services.feedback_service.quality_report",
        notes="Reports readiness; never triggers retraining.",
    ),
)

AGENTS_BY_NAME: dict[str, AgentSpec] = {spec.name: spec for spec in AGENTS}


@dataclass(frozen=True)
class WorkflowStep:
    agent: str
    reads: tuple[str, ...] = field(default_factory=tuple)
    """Which earlier steps' output this one consumes — the reason the order is
    fixed, and the thing a supervisor would have to respect however clever it
    was allowed to be."""


@dataclass(frozen=True)
class Workflow:
    name: str
    trigger: str
    steps: tuple[WorkflowStep, ...]
    ends_at: str
    """What the workflow is waiting for when it finishes. Named so an
    incomplete pipeline reads as incomplete."""
    notes: str = ""


WORKFLOWS: tuple[Workflow, ...] = (
    Workflow(
        name="lead_intelligence",
        trigger="POST /ai/leads/{id}/run-intelligence, or lead import",
        steps=(
            WorkflowStep("research"),
            WorkflowStep("buying_signals", reads=("research",)),
            WorkflowStep("icp_matching", reads=("research", "buying_signals")),
            WorkflowStep("lead_scoring", reads=("research", "buying_signals", "icp_matching")),
        ),
        ends_at=GATE_1,
    ),
    Workflow(
        name="outreach_draft",
        trigger="POST /outreach/generate",
        steps=(
            WorkflowStep("research"),
            # Two campaign passes: the first emits the case-study query RAG
            # answers, the second computes grounding from what came back.
            WorkflowStep("campaign", reads=("research",)),
            WorkflowStep("rag", reads=("campaign",)),
            WorkflowStep("outreach", reads=("research", "campaign", "rag")),
        ),
        notes="campaign runs twice — see agents/supervisor/workflow.py",
        ends_at=GATE_2,
    ),
    Workflow(
        name="reply_handling",
        trigger="POST /outreach/replies/webhook",
        steps=(WorkflowStep("reply_intent"),),
        ends_at="human reviews the suggested action",
    ),
    Workflow(
        name="revenue_forecast",
        trigger="POST /ai/forecast/run, or a recorded meeting outcome",
        steps=(WorkflowStep("revenue_forecasting"),),
        ends_at="stored forecast, reviewed by leadership",
    ),
)

WORKFLOWS_BY_NAME: dict[str, Workflow] = {flow.name: flow for flow in WORKFLOWS}


def unwired() -> tuple[AgentSpec, ...]:
    """Agents that exist and pass their tests but that no code path reaches.

    Surfaced through `GET /ai/agents` rather than left as a comment: an AI
    Center that lists twelve agents implies twelve working agents.
    """

    return tuple(spec for spec in AGENTS if spec.invoked_by is None)


def describe() -> dict[str, Any]:
    """Serialisable capability map for the AI Center."""

    return {
        "agents": [
            {
                "name": spec.name,
                "role": spec.role,
                "module": spec.module,
                "entry_class": spec.entry_class,
                "consumes": list(spec.consumes),
                "produces": list(spec.produces),
                "determinism": spec.determinism,
                "invoked_by": spec.invoked_by,
                "wired": spec.invoked_by is not None,
                "human_gate": spec.human_gate,
                "notes": spec.notes,
            }
            for spec in AGENTS
        ],
        "workflows": [
            {
                "name": flow.name,
                "trigger": flow.trigger,
                "ends_at": flow.ends_at,
                "steps": [{"agent": s.agent, "reads": list(s.reads)} for s in flow.steps],
            }
            for flow in WORKFLOWS
        ],
        "unwired_agents": [spec.name for spec in unwired()],
        "human_gates": [GATE_1, GATE_2],
    }


__all__ = [
    "AGENTS",
    "AGENTS_BY_NAME",
    "WORKFLOWS",
    "WORKFLOWS_BY_NAME",
    "AgentSpec",
    "Workflow",
    "WorkflowStep",
    "describe",
    "unwired",
]
