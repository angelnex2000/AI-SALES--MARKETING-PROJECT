"""Deciding which steps actually need to run.

Section 7 of the module brief is the point of the Supervisor: don't re-run
research that already exists. That is a real saving — research is the slowest
step in the intelligence chain and the outreach draft needs it too — but it is
**not** a pure optimisation, and treating it as one is how a caching layer
starts telling customers things that are no longer true.

Two rules keep reuse honest:

**Reuse carries provenance.** Every decision reports the age of what it reused,
and the orchestrator puts that age into the output's explanation. A draft
written from six-day-old research is fine; a reader has to be able to find out
that is what happened, because "I noticed you recently expanded" is a claim
about *when*.

**Age is not the only way a result goes stale.** An ICP score computed before
the tenant edited `icp_config` is not old, it is wrong — it scores the lead
against a profile nobody uses any more. `invalidated_after` carries that:
a stored result older than the config that defines it must re-run whatever its
age. Time-based TTLs alone would serve it happily for a month.

The planner is pure. It takes a snapshot and returns decisions; it never
queries anything, which is what makes every branch here testable without a
database.
"""

from dataclasses import dataclass
from typing import Any

from agents.supervisor.workflow import Step, Workflow

RUN = "run"
REUSE = "reuse"
SKIP = "skip"


@dataclass(frozen=True)
class StepPlan:
    step: str
    agent: str
    action: str
    reason: str
    reused_age_seconds: float | None = None

    @property
    def will_run(self) -> bool:
        return self.action == RUN


@dataclass(frozen=True)
class Plan:
    workflow: str
    steps: tuple[StepPlan, ...]
    forced: bool

    @property
    def to_run(self) -> tuple[StepPlan, ...]:
        return tuple(s for s in self.steps if s.will_run)

    @property
    def reused(self) -> tuple[StepPlan, ...]:
        return tuple(s for s in self.steps if s.action == REUSE)

    def describe(self) -> dict[str, Any]:
        return {
            "workflow": self.workflow,
            "forced": self.forced,
            "steps": [
                {
                    "step": s.step,
                    "agent": s.agent,
                    "action": s.action,
                    "reason": s.reason,
                    "reused_age_seconds": s.reused_age_seconds,
                }
                for s in self.steps
            ],
            "will_run": [s.step for s in self.to_run],
            "reused": [s.step for s in self.reused],
        }


def _decide(step: Step, snapshot: dict[str, Any], *, force: bool) -> StepPlan:
    if step.reuse_within_seconds is None or step.artifact is None:
        return StepPlan(step.name, step.agent, RUN, "step has no reusable artifact")

    if force:
        return StepPlan(step.name, step.agent, RUN, "caller requested a forced refresh")

    stored = snapshot.get(step.artifact) or {}
    if not stored.get("exists"):
        return StepPlan(step.name, step.agent, RUN, f"no stored {step.artifact} for this lead")

    age = stored.get("age_seconds")
    if age is None:
        return StepPlan(step.name, step.agent, RUN, f"stored {step.artifact} has no timestamp")

    if stored.get("invalidated_after") is not None and float(age) > float(
        stored["invalidated_after"]
    ):
        # Not old — wrong. Scored against a profile the tenant has since changed.
        return StepPlan(
            step.name,
            step.agent,
            RUN,
            f"stored {step.artifact} predates a configuration change that defines it",
        )

    if float(age) > step.reuse_within_seconds:
        return StepPlan(
            step.name,
            step.agent,
            RUN,
            (
                f"stored {step.artifact} is {_days(age)} old, beyond this workflow's "
                f"{_days(step.reuse_within_seconds)} tolerance"
            ),
        )

    return StepPlan(
        step.name,
        step.agent,
        REUSE,
        (
            f"reusing {step.artifact} from {_days(age)} ago, within this workflow's "
            f"{_days(step.reuse_within_seconds)} tolerance"
        ),
        reused_age_seconds=float(age),
    )


def _days(seconds: float | int) -> str:
    seconds = float(seconds)
    if seconds < 3600:
        return f"{seconds / 60:.0f} minutes"
    if seconds < 86400:
        return f"{seconds / 3600:.0f} hours"
    return f"{seconds / 86400:.1f} days"


def plan(
    workflow: Workflow, *, snapshot: dict[str, Any] | None = None, force: bool = False
) -> Plan:
    """Which steps run, which reuse stored output, and why for each.

    `snapshot` maps an artifact name to `{exists, age_seconds, invalidated_after}`
    and is assembled by the orchestrator, which is the layer allowed to query.
    """

    snapshot = snapshot or {}
    return Plan(
        workflow=workflow.name,
        steps=tuple(_decide(step, snapshot, force=force) for step in workflow.steps),
        forced=force,
    )


__all__ = ["REUSE", "RUN", "SKIP", "Plan", "StepPlan", "plan"]
