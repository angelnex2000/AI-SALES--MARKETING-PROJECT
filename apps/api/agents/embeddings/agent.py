"""Embeddings agent.

Thin `BaseAgent` wrapper over `model.py`, so embedding is reachable through
the same interface as every other agent while the real client stays testable
on its own.

Accepts either `{"text": "..."}` or `{"texts": [...]}`; batching matters
because indexing a document is hundreds of chunks and one call each would be
hundreds of round trips.
"""

from typing import Any

from agents.base import BaseAgent
from agents.embeddings import model
from agents.embeddings.model import EMBEDDING_DIM, EmbeddingUnavailableError

__all__ = ["EMBEDDING_DIM", "EmbeddingUnavailableError", "EmbeddingsAgent"]


class EmbeddingsAgent(BaseAgent):
    """Shared by RAG retrieval and any future ICP/campaign text similarity —
    one embedding model, not duplicated per feature, because vectors from
    different models cannot be compared to each other."""

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        texts = input_data.get("texts")
        if texts is None:
            single = input_data.get("text")
            texts = [single] if single else []

        # Empty input is not an error and must not cost an API call.
        if not texts:
            return {**model.describe(), "vectors": [], "available": model.is_configured()}

        vectors = await model.embed(list(texts))
        return {
            **model.describe(),
            "vectors": vectors,
            "available": True,
            # Convenience for single-text callers, which are the common case.
            "vector": vectors[0] if vectors else None,
        }
