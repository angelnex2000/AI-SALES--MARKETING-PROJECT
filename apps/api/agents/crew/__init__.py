"""CrewAI multi-agent skeleton — Phase 9 Module 4.

A CrewAI `Crew` over this platform's existing agents. Three things about how it
is put together, because the obvious reading of the module brief would quietly
undo work from earlier phases:

**The CrewAI agents are given tools, not personalities.** The brief's skeleton
creates `Agent(role=..., goal=..., backstory=...)` with no tools, so
`crew.kickoff()` has a language model *produce* the research report and the
"lead intelligence report" from a prompt. That would mean the lead score — the
number a rep prioritises their day by — comes from an LLM guessing rather than
from the trained model measured at ROC-AUC 0.62, and the email would skip
`validator.py` entirely. Here each Crew agent is handed tools that call the
real agents, so CrewAI does the coordinating and the existing pipeline still
does the work. That is what the brief's own Key Principle asks for: "CrewAI
coordinates agents, but your backend still controls security, database writes,
validation, and human approvals."

**Nothing here is on the default path.** `AIOrchestrator` remains the
orchestrator for every production route. This is an alternative front-end,
reached only through its own endpoint, so a CrewAI upgrade cannot take the
lead-intelligence pipeline down with it.

**Imports are guarded.** `crewai` is an optional dependency (see
`requirements-crewai.txt`). If it is not installed the API still boots and only
the crew endpoint fails, with a message saying what to install — rather than
the whole application failing at import.
"""

from typing import Any

CREWAI_INSTALL_HINT = (
    "CrewAI is an optional dependency for the Phase 9 Module 4 skeleton. "
    "Install it with: pip install -r requirements-crewai.txt"
)


class CrewUnavailableError(RuntimeError):
    """`crewai` is not installed in this environment."""


def crewai_available() -> bool:
    """Whether the optional dependency is importable.

    Checked at call time rather than cached at import: a worker image may have
    it while the API image does not, and the answer should reflect the process
    actually asked.
    """

    try:
        import crewai  # noqa: F401
    except Exception:
        return False
    return True


def require_crewai() -> Any:
    """Import `crewai`, or raise something a reader can act on."""

    try:
        import crewai
    except Exception as exc:  # noqa: BLE001 — any import failure is the same answer here
        raise CrewUnavailableError(f"{CREWAI_INSTALL_HINT} (import failed: {exc})") from exc
    return crewai


__all__ = [
    "CREWAI_INSTALL_HINT",
    "CrewUnavailableError",
    "crewai_available",
    "require_crewai",
]
