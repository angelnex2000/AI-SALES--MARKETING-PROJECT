from typing import Any

from agents.base import BaseAgent
from agents.embeddings.agent import EmbeddingsAgent

NO_VERIFIED_PROOF = "No verified company proof found."
"""RAG safety rule (Module 6): if nothing relevant is retrieved, callers
must fall back to a safer generic message rather than inventing a claim —
never fabricate a case study or product fact."""


class RAGRetriever(BaseAgent):
    """Retrieves grounding context from a tenant's own KnowledgeChunk rows
    (pgvector similarity search, scoped by company_id — never across
    tenants) before an agent generates customer-facing text. Placeholder:
    always returns no matches, so callers correctly exercise the
    NO_VERIFIED_PROOF fallback path now; the actual pgvector query is added
    once KnowledgeChunk has real embedded content to search.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        await EmbeddingsAgent().run({"text": input_data.get("query", "")})
        return {
            "model_version": "rag-stub-v0",
            "chunks": [],
            "grounded": False,
            "fallback_note": NO_VERIFIED_PROOF,
        }