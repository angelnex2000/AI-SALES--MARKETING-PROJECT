"""Campaign Agent — an AI *planner*, not an email generator.

It decides who to target, why, and with what approach. It writes no customer
text; that is the Personalized Outreach Agent's job, behind Gate 2.

Two things this agent will not do:

**It never names a case study from its own knowledge.** It emits a
`case_study_query` for RAG to answer against the tenant's own documents. If
retrieval returns nothing, the plan carries the `NO_VERIFIED_PROOF` note and
downstream emails must avoid specific claims. A planner that confidently
recommends "use the CityCare case study" to a tenant who has never uploaded
one has invented a customer.

**It does not query the database.** Audience selection is a SQL problem and
lives in `campaign_service`; this agent receives candidate statistics and
decides. That keeps it independently testable with mock input, like every
other agent here.
"""

from typing import Any

from agents.base import BaseAgent
from agents.campaign import rules

MODEL_NAME = "campaign"
MODEL_VERSION = "campaign-rules-v1"


class CampaignAgent(BaseAgent):
    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        goal = input_data.get("campaign_goal")
        industry = input_data.get("industry")
        audience = input_data.get("audience") or {}
        proof = input_data.get("proof") or {}

        strategy = rules.build_strategy(goal=goal, industry=industry)
        selected = int(audience.get("selected") or 0)
        grounded = bool(proof.get("grounded"))

        return {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "campaign_name": self._name(goal=goal, industry=industry),
            "email_style": strategy.email_style,
            "cta": strategy.cta,
            "sequence_length": strategy.sequence_length,
            "case_study_query": strategy.case_study_query,
            # Only ever what RAG actually returned.
            "recommended_case_study": proof.get("title") if grounded else None,
            "grounded": grounded,
            "proof_note": None if grounded else proof.get("fallback_note"),
            "audience_size": selected,
            "confidence": self._confidence(selected=selected, grounded=grounded),
            "explanation": self._explanation(
                strategy=strategy, audience=audience, grounded=grounded, proof=proof
            ),
        }

    def _name(self, *, goal: str | None, industry: str | None) -> str:
        readable_goal = (goal or "").replace("_", " ").title() or None
        parts = [p for p in (industry, readable_goal) if p]
        return " — ".join(parts) if parts else "Untitled campaign"

    def _confidence(self, *, selected: int, grounded: bool) -> float:
        """How much to trust this plan.

        A plan targeting nobody is worth nothing however good the strategy is,
        so an empty audience floors it. Grounding matters too: an ungrounded
        campaign can still run, but its emails cannot make claims.
        """

        if selected == 0:
            return 0.0
        score = 0.6
        if selected >= 10:
            score += 0.2
        if grounded:
            score += 0.2
        return round(min(score, 1.0), 2)

    def _explanation(
        self,
        *,
        strategy: rules.CampaignStrategy,
        audience: dict[str, Any],
        grounded: bool,
        proof: dict[str, Any],
    ) -> str:
        selected = int(audience.get("selected") or 0)
        considered = int(audience.get("considered") or 0)

        if selected == 0:
            # The most common real outcome, and the one a naive implementation
            # reports as a bare "0 leads" with no way to act on it.
            blocker = audience.get("limiting_criterion")
            detail = f" The tightest filter was {blocker}." if blocker else ""
            return (
                f"No leads matched out of {considered} considered.{detail} "
                "Relax the criteria, or run lead intelligence on more leads first."
            )

        parts = [f"{selected} of {considered} leads matched.", strategy.rationale]
        if grounded:
            parts.append(f"Grounded in: {proof.get('title')}.")
        else:
            parts.append(
                "No approved case study was found, so emails in this campaign "
                "must avoid specific claims."
            )
        return " ".join(parts)
