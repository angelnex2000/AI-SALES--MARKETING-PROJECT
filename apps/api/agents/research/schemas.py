"""Input and output contracts for the Research Agent.

The central design choice here is that **evidence and inference are different
types**. A fact we found ("expanded telemedicine services", from a press
release) and a guess we made ("probably struggling with patient inquiry
volume") are both useful, but conflating them is how an AI system ends up
telling a prospect something it invented — these fields feed the Personalized
Outreach Agent, whose output passes Gate 2 and lands in a customer's inbox.

So `recent_news` carries `Evidence` (claim + where it came from) while
`pain_points` and `sales_opportunities` carry `Hypothesis` (statement + what
led us to infer it). Downstream code cannot accidentally render a hypothesis
as a fact, because the shape is different.
"""

from pydantic import BaseModel, Field


class ResearchInput(BaseModel):
    """What the orchestrator passes in.

    Deliberately a plain payload rather than a database session: agents must
    stay independently testable with mock input, which means they never query
    the database themselves.
    """

    lead_id: str
    company_name: str
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    city: str | None = None
    employees: int | None = None
    annual_revenue: float | None = None
    source: str | None = None
    """How the lead arrived — linkedin, csv_import, crm_sync, webform."""
    crm_notes: list[str] = Field(default_factory=list)
    """Human-written notes already on the lead. Real signal: a rep who logged
    "they mentioned budget approval in Q3" knows something no website says."""


class Evidence(BaseModel):
    """Something we actually found, with its provenance."""

    claim: str
    source: str
    """Where this came from — a URL, `crm_notes`, or `lead_database`. Never
    empty: an unattributable claim is an inference, not evidence."""


class Hypothesis(BaseModel):
    """Something we inferred. Not a fact, and must never be presented as one."""

    statement: str
    basis: str
    """What led us here — e.g. "healthcare + >500 employees". Makes the guess
    auditable, and gives the outreach prompt something to hedge with."""


class ResearchOutput(BaseModel):
    """The structured report. Maps onto `ResearchReport` (which adds the
    AIOutputMixin columns: model_name, model_version, confidence, explanation).
    """

    company_summary: str
    industry_insights: str | None = None
    company_size_estimate: str | None = None
    recent_news: list[Evidence] = Field(default_factory=list)
    pain_points: list[Hypothesis] = Field(default_factory=list)
    sales_opportunities: list[Hypothesis] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    """Evidence *coverage*, not truth probability — see confidence.py."""
    explanation: str
    """Why the report looks the way it does. Required by AIOutputMixin on
    every AI output so a Sales Manager can see reasoning, not just a number."""
