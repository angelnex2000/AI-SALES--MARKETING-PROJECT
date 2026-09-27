"""Embedding model client.

One embedding model for the whole platform — RAG retrieval, and any future
ICP or campaign text similarity. Not duplicated per feature, because
**vectors from different models are not comparable**: a MiniLM vector and an
OpenAI vector of the same length describe different spaces entirely, and
cosine similarity between them returns a number that means nothing. That is
why `MODEL_NAME` is recorded alongside every stored vector
(`KnowledgeEmbedding.embedding_model`) and why the retriever must filter on
it rather than assuming.

Chosen: OpenAI `text-embedding-3-small` at 1536 dimensions, matching the
existing pgvector column. The trade-off accepted here is that text sent for
embedding leaves our infrastructure — relevant because RAG embeds a tenant's
own case studies and pricing documents. A local model (sentence-transformers)
would keep that in-house but adds torch to the image; if data residency ever
becomes a requirement, swap this module and re-embed, which is exactly what
recording `embedding_model` per row makes possible.
"""

import hashlib
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = "text-embedding-3-small"
MODEL_VERSION = "openai-text-embedding-3-small-v1"
EMBEDDING_DIM = 1536
"""Must equal `app/models/knowledge.py::EMBEDDING_DIM` and the `Vector(...)`
column width. Changing the model means changing all three **and** re-embedding
every stored chunk — old vectors are not translatable to a new space."""

MAX_BATCH = 100
"""Chunks per API call. Embedding a 500-chunk document one call at a time is
500 round trips; batching is the difference between seconds and minutes."""

# Per-process memo. Deliberately not Redis: embeddings are deterministic for a
# given (model, text), the win is avoiding repeat cost inside one indexing run,
# and a distributed cache here would add a dependency for a marginal gain.
_cache: dict[str, list[float]] = {}
_CACHE_LIMIT = 2048


class EmbeddingUnavailableError(RuntimeError):
    """No API key configured, or the provider rejected the request. Callers
    must treat this as "cannot ground" and fall back — never as "no matches",
    which would silently downgrade a RAG answer to an ungrounded one."""


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{MODEL_NAME}\x00{text}".encode()).hexdigest()


def is_configured() -> bool:
    return bool(settings.OPENAI_API_KEY)


async def embed(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, preserving input order.

    Raises `EmbeddingUnavailableError` rather than returning zeros: a zero
    vector is a valid point in the space and would silently match nothing (or
    everything), which is far harder to debug than an explicit failure.
    """

    if not texts:
        return []
    if not is_configured():
        raise EmbeddingUnavailableError(
            "OPENAI_API_KEY is not set — embeddings and RAG grounding are unavailable"
        )

    results: list[list[float] | None] = [None] * len(texts)
    pending: list[tuple[int, str]] = []

    for index, text in enumerate(texts):
        cached = _cache.get(_cache_key(text))
        if cached is not None:
            results[index] = cached
        else:
            pending.append((index, text))

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    for start in range(0, len(pending), MAX_BATCH):
        batch = pending[start : start + MAX_BATCH]
        try:
            response = await client.embeddings.create(
                model=MODEL_NAME, input=[text for _, text in batch]
            )
        except Exception as exc:
            logger.error("embedding request failed", exc_info=exc)
            raise EmbeddingUnavailableError(str(exc)) from exc

        for (index, text), item in zip(batch, response.data, strict=True):
            vector = list(item.embedding)
            _validate(vector)
            results[index] = vector
            if len(_cache) < _CACHE_LIMIT:
                _cache[_cache_key(text)] = vector

    # `None` here would mean the provider returned fewer vectors than we asked
    # for, which `strict=True` above already rules out — this is a guard
    # against a future change silently dropping one.
    if any(v is None for v in results):
        raise EmbeddingUnavailableError("provider returned fewer embeddings than requested")
    return [v for v in results if v is not None]


async def embed_one(text: str) -> list[float]:
    vectors = await embed([text])
    return vectors[0]


def _validate(vector: list[float]) -> None:
    if len(vector) != EMBEDDING_DIM:
        # Storing a wrong-width vector fails at the pgvector column anyway, but
        # much later and with a far less obvious message.
        raise EmbeddingUnavailableError(
            f"expected {EMBEDDING_DIM}-dimensional embedding, got {len(vector)}"
        )


def describe() -> dict[str, Any]:
    """Identity to store beside every vector, so a later model change is
    detectable rather than silently corrupting comparisons."""

    return {
        "embedding_model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "dimensions": EMBEDDING_DIM,
    }
