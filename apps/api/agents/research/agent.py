"""Research Agent — MVP implementation.

A pipeline, not a prompt:

    payload -> collect sources -> derive claims -> score coverage -> validate

This version reasons only over data the tenant already holds (the lead record
and its CRM notes). It produces no unattributed claims: everything in
`recent_news` carries a source, and everything it guesses is typed as a
`Hypothesis` with the basis for the guess recorded.

The LLM version replaces the `_derive_*` methods only. The contract, the
confidence calculation, the source collection and the validation all stay —
which is the point of building the pipeline before the model. `prompts.py`
holds the instruction that will drive it.
"""

from typing import Any

from agents.base import BaseAgent
from agents.research import confidence as confidence_mod
from agents.research.schemas import Evidence, Hypothesis, ResearchInput, ResearchOutput
from agents.research.source_collector import collect

MODEL_NAME = "research"
MODEL_VERSION = "research-rules-v1"
"""Reported when the agent ran offline — lead data and CRM notes only."""
WEB_MODEL_VERSION = "research-web-v1"
"""Reported when live sourcing contributed. Two versions from one agent, the
same pattern `lead_scoring` uses for trained-vs-heuristic: a report built from
live news and one built from a lead record are different artifacts, and a
reader tracing a claim months later must be able to tell which they have."""
"""Bumped from research-stub-v0. Every stored report records the version that
produced it, so reports from different logic stay comparable and a bad release
is traceable — `model_version` resolves against ModelRegistryEntry."""

# Industry-specific inferences, keyed by lowercase industry. Deliberately a
# lookup table rather than prose buried in code: a sales lead is better placed
# than an engineer to say whether these are right, and this way they can read
# and correct them.
INDUSTRY_PLAYBOOK: dict[str, dict[str, list[str]]] = {
    "healthcare": {
        "pain_points": ["High patient inquiry volume", "Manual appointment coordination"],
        "opportunities": ["AI chatbot for patient support", "Automated appointment reminders"],
    },
    "saas": {
        "pain_points": ["High trial-to-paid drop-off", "Support load scaling with signups"],
        "opportunities": ["Automated onboarding sequences", "In-product support deflection"],
    },
    "finance": {
        "pain_points": ["Compliance-heavy manual review", "Slow client onboarding"],
        "opportunities": ["Document processing automation", "KYC workflow automation"],
    },
    "retail": {
        "pain_points": ["Seasonal support spikes", "Fragmented customer data"],
        "opportunities": ["Seasonal support automation", "Unified customer profile"],
    },
    "manufacturing": {
        "pain_points": ["Long quote turnaround", "Manual distributor coordination"],
        "opportunities": ["Quote automation", "Partner portal automation"],
    },
}

LARGE_HEADCOUNT = 500
SMALL_HEADCOUNT = 50


class ResearchAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        payload = ResearchInput.model_validate(input_data)
        context, sources = await collect(payload)
        web_sources = context["web"]

        news = self._derive_evidence(payload, web_sources)
        pain_points = self._derive_pain_points(payload)
        opportunities = self._derive_opportunities(payload)

        # Only externally-sourced items count as news. `news` also carries the
        # lead-origin line and CRM notes, and counting those inflated coverage
        # twice over: "Lead originated from linkedin" is not news, and CRM
        # notes already score through their own `crm_notes_present` signal, so
        # a lead with notes was collecting 0.40 of coverage for one fact.
        external_news = len(getattr(web_sources, "news", None) or [])
        score, reasons = confidence_mod.score(payload=payload, news_count=external_news)

        report = ResearchOutput(
            company_summary=self._summary(payload),
            industry_insights=self._industry_insights(payload),
            company_size_estimate=self._size_estimate(payload),
            recent_news=news,
            pain_points=pain_points,
            sales_opportunities=opportunities,
            sources=sources,
            confidence=score,
            explanation=self._explanation(score, reasons),
        )
        # Round-trip through the schema so a malformed report fails here, in
        # the agent, rather than at the database write or on the page.
        return {
            "model_name": MODEL_NAME,
            "model_version": WEB_MODEL_VERSION if getattr(web_sources, "used", False) else MODEL_VERSION,
            **report.model_dump(),
        }

    # ---------------------------------------------------------------- claims

    def _derive_evidence(self, payload: ResearchInput, web_sources=None) -> list[Evidence]:
        """Only things we can actually attribute.

        Web results come first because they are the only claims here about the
        *outside world*; the rest describe our own CRM. Each carries the URL it
        came from, so a rep about to repeat it can see the source — an
        unattributable claim would be an inference, and `Evidence` refuses to
        carry one.

        Returning an empty list stays correct and honest: it lowers confidence
        through the `recent_news_found` signal, which is exactly what a rep
        needs to know before trusting the report.
        """

        evidence: list[Evidence] = []
        for item in getattr(web_sources, "news", None) or []:
            published = item.get("published")
            claim = f"{item['claim']} ({published})" if published else item["claim"]
            evidence.append(Evidence(claim=claim, source=item["source"]))

        if payload.source:
            evidence.append(
                Evidence(claim=f"Lead originated from {payload.source}", source="lead_database")
            )
        # Cap the notes: a lead with 200 logged notes would otherwise bury the
        # report, and the newest few carry the most signal.
        for note in payload.crm_notes[:5]:
            evidence.append(Evidence(claim=note, source="crm_notes"))
        return evidence

    def _derive_pain_points(self, payload: ResearchInput) -> list[Hypothesis]:
        hypotheses: list[Hypothesis] = []

        playbook = INDUSTRY_PLAYBOOK.get((payload.industry or "").lower())
        if playbook:
            hypotheses.extend(
                Hypothesis(statement=statement, basis=f"industry = {payload.industry}")
                for statement in playbook["pain_points"]
            )

        if payload.employees is not None:
            if payload.employees > LARGE_HEADCOUNT:
                hypotheses.append(
                    Hypothesis(
                        statement="Large-scale customer support operations",
                        basis=f"headcount ~{payload.employees} (> {LARGE_HEADCOUNT})",
                    )
                )
            elif payload.employees < SMALL_HEADCOUNT:
                hypotheses.append(
                    Hypothesis(
                        statement="Small team stretched across many functions",
                        basis=f"headcount ~{payload.employees} (< {SMALL_HEADCOUNT})",
                    )
                )
        return hypotheses

    def _derive_opportunities(self, payload: ResearchInput) -> list[Hypothesis]:
        playbook = INDUSTRY_PLAYBOOK.get((payload.industry or "").lower())
        if not playbook:
            # No sector angle. Say nothing rather than inventing one — a
            # generic "AI automation opportunity" on every lead is noise a rep
            # learns to scroll past, which devalues the real ones.
            return []
        return [
            Hypothesis(statement=statement, basis=f"industry = {payload.industry}")
            for statement in playbook["opportunities"]
        ]

    # ----------------------------------------------------------------- prose

    def _summary(self, payload: ResearchInput) -> str:
        clauses = []
        if payload.industry:
            clauses.append(f"operates in the {payload.industry} sector")
        else:
            clauses.append("has no industry recorded")
        location = payload.city or payload.country
        if location:
            clauses.append(f"based in {location}")
        if payload.employees:
            clauses.append(f"with roughly {payload.employees} employees")
        return f"{payload.company_name} {', '.join(clauses)}."

    def _industry_insights(self, payload: ResearchInput) -> str | None:
        if not payload.industry:
            return None
        if payload.industry.lower() not in INDUSTRY_PLAYBOOK:
            return f"No sector playbook recorded for {payload.industry}."
        return (
            f"{payload.industry} organisations commonly invest in customer engagement "
            "and workflow automation."
        )

    def _size_estimate(self, payload: ResearchInput) -> str | None:
        if payload.employees is None:
            return None
        if payload.employees < SMALL_HEADCOUNT:
            return f"Small (~{payload.employees} employees)"
        if payload.employees <= LARGE_HEADCOUNT:
            return f"Mid-market (~{payload.employees} employees)"
        return f"Enterprise (~{payload.employees} employees)"

    def _explanation(self, score: float, reasons: list[str]) -> str:
        headline = (
            "Profile assembled from available lead data"
            if confidence_mod.is_actionable(score)
            else "Insufficient data for a reliable profile"
        )
        return f"{headline}. Coverage {score:.2f} — {'; '.join(reasons)}."
