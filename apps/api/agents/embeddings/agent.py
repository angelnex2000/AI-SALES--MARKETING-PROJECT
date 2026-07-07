from typing import Any

from agents.base import BaseAgent

EMBEDDING_DIM = 1536
"""Matches KnowledgeChunk.embedding's dimension (app/models/knowledge.py) —
change both together if the embedding model changes."""


class EmbeddingsAgent(BaseAgent):
    """Shared by RAG retrieval and any future ICP/campaign text similarity
    matching — one embedding model, not duplicated per feature. Placeholder:
    returns a zero vector of the right dimension so callers can be wired
    end-to-end before a real embedding model (e.g. OpenAI
    text-embedding-3-small) is plugged in.
    """

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return {"model_version": "embeddings-stub-v0", "vector": [0.0] * EMBEDDING_DIM}