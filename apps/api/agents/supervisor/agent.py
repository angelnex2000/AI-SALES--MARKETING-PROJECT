"""The Supervisor Agent — Phase 9 Module 2.

"The Supervisor Agent should orchestrate work, not perform it." Taken
literally, which is why this class **cannot** do any work: it has no database
handle, imports no other agent, and returns a plan rather than a result. The
execution layer is `AIOrchestrator`, which is the layer allowed to query and
persist.

That split is what makes the brief's section 6 testable. "Does research already
exist? Then skip it" is a decision, and decisions belong somewhere they can be
asserted about without a database, a Celery broker, or an LLM key.

## Why this is not the CrewAI package

CrewAI is a good fit for its intended shape: an LLM that reads a goal and
decides which specialist to delegate to. This system does not have that shape,
and adopting the library would mean paying for it and then switching off the
one feature that distinguishes it.

  * **There is nothing to delegate.** The order is fixed by data dependency —
    Buying Signals reads `research.recent_news`, ICP reads the signals, Scoring
    reads all three. A model choosing the order picks between one correct
    sequence and several broken ones.
  * **The outputs must be reproducible.** A lead score is what a rep
    prioritises their day by, and `AIInteractionLog` exists so a wrong answer
    can be replayed. Non-deterministic sequencing breaks both.
  * **Cost.** It pulls a large dependency tree into an image where torch was
    already declined twice on size grounds, to replace roughly 200 lines that
    are already covered by tests.

So the *concepts* are adopted — Agent, Task, Crew, tools, scoped memory — and
the runtime is ours. Revisit if a workflow ever appears whose shape genuinely
is not knowable in advance; nothing in Phases 1-9 is.
"""

from typing import Any

from agents.base import BaseAgent
from agents.supervisor import planner
from agents.supervisor.workflow import WORKFLOWS_BY_NAME

MODEL_NAME = "supervisor"
MODEL_VERSION = "supervisor-declarative-v1"


class UnknownWorkflowError(KeyError):
    """Asked to plan something that is not a declared workflow."""


class SupervisorAgent(BaseAgent):
    """Plans a workflow. Runs nothing."""

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        name = str(input_data.get("workflow") or "")
        workflow = WORKFLOWS_BY_NAME.get(name)
        if workflow is None:
            raise UnknownWorkflowError(
                f"{name!r} is not a declared workflow; known: {sorted(WORKFLOWS_BY_NAME)}"
            )

        decided = planner.plan(
            workflow,
            snapshot=input_data.get("snapshot") or {},
            force=bool(input_data.get("force")),
        )

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "plan": decided.describe(),
            "ends_at": workflow.ends_at,
            "explanation": self._explain(decided, workflow.ends_at),
        }

    def _explain(self, decided: planner.Plan, ends_at: str) -> str:
        running = [s.step for s in decided.to_run]
        reused = decided.reused
        text = (
            f"Running {len(running)} of {len(decided.steps)} step(s): "
            f"{', '.join(running) or 'none'}."
        )
        if reused:
            # Provenance, not trivia: a draft written from six-day-old research
            # is fine, but a reader has to be able to discover that it was.
            details = "; ".join(f"{s.step} ({s.reason})" for s in reused)
            text += f" Reusing stored output for {details}."
        if decided.forced:
            text += " Forced refresh — nothing was reused."
        text += f" The workflow stops at {ends_at}."
        return text


__all__ = ["MODEL_NAME", "MODEL_VERSION", "SupervisorAgent", "UnknownWorkflowError"]
