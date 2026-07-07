from typing import Any

from agents.base import BaseAgent
from agents.rag.retriever import RAGRetriever


class OutreachAgent(BaseAgent):
    """Placeholder implementation. The real version drafts the email with
    an LLM (see prompts.py), grounded in RAGRetriever's retrieved case
    studies and product facts. If no relevant document is found, it must
    fall back to a safer generic message rather than inventing a claim —
    see RAGRetriever.NO_VERIFIED_PROOF. Output always lands in EmailDraft
    with status=PENDING_APPROVAL — Gate 2 never bypassed here.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        context = await RAGRetriever().run({"query": input_data.get("pain_points", "")})
        return {
            "model_version": "outreach-stub-v0",
            "subject": "",
            "body": "",
            "grounded": context["grounded"],
            "explanation": context["fallback_note"] if not context["grounded"] else "",
        }