"""Vector similarity helpers.

Used for in-memory comparison and for tests. **Production RAG retrieval does
not use this** — it pushes the search into Postgres with pgvector's `<=>`
operator, so the database returns the top-k rows instead of the application
loading every chunk a tenant owns into memory to sort them.

These live here for the cases where the vectors are already in hand: ranking a
handful of candidates, and asserting in tests that "AI chatbot for hospital
patient support" really is closer to "Automation for healthcare customer
inquiries" than to something unrelated.
"""

import math

from agents.embeddings.model import EMBEDDING_DIM

RELEVANCE_THRESHOLD = 0.35
"""Below this, a chunk is not evidence. The RAG retriever's contract is to
return `NO_VERIFIED_PROOF` rather than the best of a bad set — cosine
similarity always yields a "closest" match, and without a floor the outreach
agent would cite the least-irrelevant document as proof of a claim."""


class DimensionMismatchError(ValueError):
    """Vectors from different models, or a malformed vector.

    Comparing them is meaningless rather than merely inaccurate: same-length
    vectors from different models describe different spaces.
    """


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. 1.0 means identical direction."""

    if len(a) != len(b):
        raise DimensionMismatchError(
            f"cannot compare {len(a)}-d and {len(b)}-d vectors — different embedding models"
        )
    if not a:
        raise DimensionMismatchError("cannot compare empty vectors")

    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        # A zero vector has no direction, so "similarity" is undefined. Return
        # 0.0 rather than dividing — but note this is the shape a stubbed or
        # failed embedding takes, which is why model.py raises instead of
        # returning zeros.
        return 0.0
    return dot / (norm_a * norm_b)


def is_relevant(score: float) -> bool:
    return score >= RELEVANCE_THRESHOLD


def rank(
    query: list[float], candidates: list[tuple[str, list[float]]], *, top_k: int = 5
) -> list[tuple[str, float]]:
    """Rank `(id, vector)` candidates against a query vector, best first.

    Only returns candidates above `RELEVANCE_THRESHOLD`: an empty result is a
    meaningful answer ("we have nothing relevant"), and padding it with weak
    matches is how a grounded system starts citing irrelevant documents.
    """

    scored = []
    for identifier, vector in candidates:
        score = cosine_similarity(query, vector)
        if is_relevant(score):
            scored.append((identifier, score))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_k]


def validate_dimension(vector: list[float]) -> None:
    if len(vector) != EMBEDDING_DIM:
        raise DimensionMismatchError(
            f"expected {EMBEDDING_DIM} dimensions, got {len(vector)}"
        )
