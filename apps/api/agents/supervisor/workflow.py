"""Declarative task graphs — Phase 9 Module 2.

The Supervisor coordinates work; it never does the work. That separation is
only real if the workflow is data the supervisor reads rather than control flow
it contains, so each workflow is declared here and `planner.py` turns one plus
a freshness snapshot into a plan.

## Staleness tolerance belongs to the CONSUMER, not the producer

The single most important thing in this file. `research` appears in two
workflows with two different TTLs, and that is deliberate:

  * `lead_intelligence` reuses a research report up to **30 days** old. It
    feeds a ranking — "call this lead before that one" — and month-old
    firmographics still rank correctly.
  * `outreach_draft` reuses one only up to **7 days**. It feeds a sentence in
    a customer's inbox: "I noticed you recently expanded". Month-old news
    asserted as current is us telling a prospect something false about their
    own company.

A TTL attached to the agent would force one number to serve both, and whichever
was chosen would be wrong for the other. So the number lives on the step.

## Payload scope is how agent memory is restricted

Module 2 section 8 asks that each agent see only the memory it needs. In this
architecture agents cannot fetch anything — they receive a payload and have no
database handle — so scoping the payload *is* the permission model, and it is
stricter than tool permissions: an agent cannot reach beyond its scope even
incorrectly, because there is nothing to reach with. `payload_scope` declares
the keys a step may be given and `scoped_payload()` enforces it by
construction, so "the Outreach Agent must not see the whole lead record" is a
test rather than a convention.
"""

from dataclasses import dataclass, field
from typing import Any

# Named so a reader sees the intent rather than a number of seconds.
HOUR = 3600
DAY = 24 * HOUR


@dataclass(frozen=True)
class Step:
    name: str
    agent: str
    """Registry name. The step is the unit of work; the agent is who does it."""
    reads: tuple[str, ...] = field(default_factory=tuple)
    """Earlier steps whose output this one consumes. This is what fixes the
    order — there is no judgement for a supervisor to exercise."""
    payload_scope: tuple[str, ...] = field(default_factory=tuple)
    """Context keys this step's agent may receive. Enforced, not advisory."""
    reuse_within_seconds: int | None = None
    """How old a stored result may be before this step must re-run. None means
    the step always runs — it has no stored artifact to reuse."""
    artifact: str | None = None
    """Freshness key the orchestrator reports on, when reuse is possible."""
    optional: bool = False
    """A failure here degrades the result rather than failing the workflow."""


@dataclass(frozen=True)
class Workflow:
    name: str
    trigger: str
    steps: tuple[Step, ...]
    ends_at: str

    def step(self, name: str) -> Step:
        for candidate in self.steps:
            if candidate.name == name:
                return candidate
        raise KeyError(name)


# The Research Agent takes a flat lead payload rather than a nested one, so the
# scope is spelled out. Declaring a tidier `("lead", "crm_notes")` would have
# been a scope that describes nothing the agent is actually handed — the same
# failure mode as an architecture map that has drifted from the code.
RESEARCH_SCOPE: tuple[str, ...] = (
    "lead_id",
    "company_name",
    "industry",
    "website",
    "country",
    "city",
    "employees",
    "annual_revenue",
    "source",
    "crm_notes",
)


LEAD_INTELLIGENCE = Workflow(
    name="lead_intelligence",
    trigger="POST /ai/leads/{id}/run-intelligence",
    ends_at="gate_1_manager_assigns",
    steps=(
        Step(
            name="research",
            agent="research",
            payload_scope=RESEARCH_SCOPE,
            reuse_within_seconds=30 * DAY,
            artifact="research",
        ),
        Step(
            name="buying_signals",
            agent="buying_signals",
            reads=("research",),
            payload_scope=("research",),
        ),
        Step(
            name="icp_matching",
            agent="icp_matching",
            reads=("research", "buying_signals"),
            payload_scope=("lead", "research", "signals", "icp_profile"),
        ),
        Step(
            name="lead_scoring",
            agent="lead_scoring",
            reads=("research", "buying_signals", "icp_matching"),
            payload_scope=("lead", "research", "signals", "icp"),
        ),
    ),
)

OUTREACH_DRAFT = Workflow(
    name="outreach_draft",
    trigger="POST /outreach/generate",
    ends_at="gate_2_exec_approves_send",
    steps=(
        Step(
            name="research",
            agent="research",
            payload_scope=RESEARCH_SCOPE,
            # Seven days, not thirty — see the module docstring. This report
            # becomes assertions in a customer's inbox.
            reuse_within_seconds=7 * DAY,
            artifact="research",
        ),
        # Campaign planning is genuinely two-phase, so it is declared as two
        # steps rather than as one step that quietly runs twice. The agent
        # emits the `case_study_query` RAG needs, and it computes `grounded`
        # from what RAG returned — so the query pass has to precede retrieval
        # and the authoritative pass has to follow it. Collapsing them into one
        # step made the declared order (campaign → rag) disagree with the order
        # the audit log actually recorded (rag → campaign), which is exactly
        # the drift these declarations exist to prevent. Two names also keep
        # the two rows distinguishable to anyone reading the trail.
        Step(
            name="campaign_query",
            agent="campaign",
            reads=("research",),
            payload_scope=("campaign_goal", "industry", "audience", "proof"),
        ),
        Step(
            name="rag",
            agent="rag",
            reads=("campaign_query",),
            payload_scope=("query", "company_id"),
            # Retrieval failing is not draft generation failing: the Outreach
            # Agent has a documented ungrounded path that forbids specific
            # claims, which is better than no email at all.
            optional=True,
        ),
        Step(
            name="campaign",
            agent="campaign",
            reads=("campaign_query", "rag"),
            payload_scope=("campaign_goal", "industry", "audience", "proof"),
        ),
        Step(
            name="outreach",
            agent="outreach",
            reads=("research", "campaign", "rag"),
            payload_scope=("recipient", "strategy", "chunks"),
        ),
    ),
)

WORKFLOWS: tuple[Workflow, ...] = (LEAD_INTELLIGENCE, OUTREACH_DRAFT)
WORKFLOWS_BY_NAME: dict[str, Workflow] = {flow.name: flow for flow in WORKFLOWS}


class PayloadScopeError(RuntimeError):
    """A step was handed context it did not declare.

    Raised rather than filtered silently: quietly dropping an undeclared key
    would turn a wiring mistake into an agent running on incomplete input,
    which surfaces later as a bad answer rather than as an error.
    """


def scoped_payload(step: Step, context: dict[str, Any]) -> dict[str, Any]:
    """Everything the step declared, and nothing else.

    Missing keys are allowed — an agent may legitimately be called with a
    partial context (no CRM notes, no retrieved chunks). Extra keys are not.
    """

    extra = set(context) - set(step.payload_scope)
    if extra:
        raise PayloadScopeError(
            f"step {step.name!r} was given undeclared context {sorted(extra)}; "
            f"declared scope is {sorted(step.payload_scope)}"
        )
    return {key: context[key] for key in step.payload_scope if key in context}


__all__ = [
    "LEAD_INTELLIGENCE",
    "OUTREACH_DRAFT",
    "WORKFLOWS",
    "WORKFLOWS_BY_NAME",
    "PayloadScopeError",
    "Step",
    "Workflow",
    "scoped_payload",
]
