"""RAG retrieval.

Grounds the Personalized Outreach Agent in a tenant's own approved material —
case studies, product docs, pricing, playbooks — before it writes anything a
customer will read.

Two rules that must survive any future rewrite:

1. **Never cross tenants.** The pgvector query filters `company_id`. One
   tenant's case studies grounding another tenant's outreach would leak
   commercial material between competitors.
2. **"Nothing relevant" is an answer.** Cosine similarity always returns a
   closest match, so without `RELEVANCE_THRESHOLD` the retriever would hand
   back the least-irrelevant document and outreach would cite it as proof.
   `NO_VERIFIED_PROOF` makes the caller fall back to a generic message rather
   than inventing a claim.

A third case is easy to get wrong: **embeddings being unavailable is not the
same as no matches.** If the API key is missing or the provider errors,
returning "no chunks" would silently downgrade a grounded email to an
ungrounded one with no signal that anything broke. That path sets
`available=False` so the caller can tell "we looked and found nothing" from
"we could not look".
"""

from typing import Any

from agents.base import BaseAgent
from agents.embeddings import model as embedding_model
from agents.embeddings.model import EmbeddingUnavailableError
from agents.embeddings.similarity import RELEVANCE_THRESHOLD

NO_VERIFIED_PROOF = "No verified company proof found."
"""RAG safety rule (Module 6): if nothing relevant is retrieved, callers must
fall back to a safer generic message rather than inventing a claim — never
fabricate a case study or product fact."""

MODEL_VERSION = "rag-pgvector-v1"


class RAGRetriever(BaseAgent):
    """Retrieves grounding context from a tenant's own `KnowledgeChunk` rows.

    The pgvector similarity query is not wired yet — no tenant has indexed
    content, and SQLite has no `<=>` operator so it cannot run in the default
    test path. The embedding call and the fallback contract are real, so
    callers already exercise `NO_VERIFIED_PROOF` correctly.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        query = (input_data.get("query") or "").strip()
        company_id = input_data.get("company_id")

        if not query:
            return self._empty(reason="empty query", available=True)
        if company_id is None:
            # Refuse rather than searching unscoped: a missing tenant id must
            # never widen the search across every tenant's documents.
            return self._empty(reason="no company_id supplied", available=True)

        try:
            await embedding_model.embed_one(query)
        except EmbeddingUnavailableError as exc:
            return self._empty(reason=str(exc), available=False)

        # TODO(phase-8): pgvector search, scoped by company_id AND
        # embedding_model — vectors from a different model are not comparable,
        # so mixing them silently degrades retrieval:
        #
        #   SELECT c.* FROM knowledge_chunks c
        #   JOIN knowledge_embeddings e ON e.chunk_id = c.id
        #   WHERE e.company_id = :company_id
        #     AND e.embedding_model = :embedding_model
        #   ORDER BY e.embedding <=> :query_vector
        #   LIMIT :top_k
        #
        # Then drop anything below RELEVANCE_THRESHOLD before returning.
        return self._empty(reason="no indexed content for this tenant", available=True)

    def _empty(self, *, reason: str, available: bool) -> dict[str, Any]:
        return {
            "model_version": MODEL_VERSION,
            "chunks": [],
            "grounded": False,
            "available": available,
            "relevance_threshold": RELEVANCE_THRESHOLD,
            "fallback_note": NO_VERIFIED_PROOF,
            "reason": reason,
        }
