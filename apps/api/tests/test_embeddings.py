"""Embeddings, similarity, and the RAG grounding contract.

The OpenAI client is stubbed — these test our logic (batching, caching,
dimension guards, thresholds), not the provider's.
"""

import math

import pytest

from agents.embeddings import model as embedding_model
from agents.embeddings.agent import EmbeddingsAgent
from agents.embeddings.model import EMBEDDING_DIM, EmbeddingUnavailableError
from agents.embeddings.similarity import (
    RELEVANCE_THRESHOLD,
    DimensionMismatchError,
    cosine_similarity,
    is_relevant,
    rank,
)
from agents.rag.retriever import NO_VERIFIED_PROOF, RAGRetriever


def vec(*values: float) -> list[float]:
    """Pad to the real dimension so guards see a well-formed vector."""

    return list(values) + [0.0] * (EMBEDDING_DIM - len(values))


@pytest.fixture(autouse=True)
def clear_cache():
    embedding_model._cache.clear()
    yield
    embedding_model._cache.clear()


class FakeEmbeddings:
    """Records calls so batching and caching are observable."""

    def __init__(self, dim=EMBEDDING_DIM):
        self.calls: list[list[str]] = []
        self.dim = dim

    async def create(self, *, model, input):
        self.calls.append(list(input))
        data = [
            type("Item", (), {"embedding": [float(len(t))] + [0.0] * (self.dim - 1)})()
            for t in input
        ]
        return type("Response", (), {"data": data})()


@pytest.fixture
def fake_openai(monkeypatch):
    fake = FakeEmbeddings()

    class FakeClient:
        def __init__(self, **_):
            self.embeddings = fake

    monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(embedding_model, "AsyncOpenAI", FakeClient)
    return fake


class TestEmbedding:
    async def test_returns_a_vector_per_input_in_order(self, fake_openai):
        vectors = await embedding_model.embed(["a", "bb", "ccc"])
        assert [v[0] for v in vectors] == [1.0, 2.0, 3.0]

    async def test_empty_input_costs_no_api_call(self, fake_openai):
        assert await embedding_model.embed([]) == []
        assert fake_openai.calls == []

    async def test_batches_rather_than_one_call_each(self, fake_openai, monkeypatch):
        """Indexing a document is hundreds of chunks; one call each would be
        hundreds of round trips."""

        monkeypatch.setattr(embedding_model, "MAX_BATCH", 10)
        await embedding_model.embed([f"chunk-{i}" for i in range(25)])
        assert len(fake_openai.calls) == 3
        assert [len(c) for c in fake_openai.calls] == [10, 10, 5]

    async def test_repeat_text_is_served_from_cache(self, fake_openai):
        await embedding_model.embed(["same text"])
        await embedding_model.embed(["same text"])
        assert len(fake_openai.calls) == 1, "identical text must not be paid for twice"

    async def test_partial_cache_hit_only_requests_the_misses(self, fake_openai):
        await embedding_model.embed(["one"])
        fake_openai.calls.clear()
        await embedding_model.embed(["one", "two"])
        assert fake_openai.calls == [["two"]]


class TestFailureIsLoud:
    """A zero vector is a valid point in the space: it would match nothing or
    everything, and debugging that is far harder than an explicit error."""

    async def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "")
        with pytest.raises(EmbeddingUnavailableError):
            await embedding_model.embed(["text"])

    async def test_provider_error_raises(self, monkeypatch):
        class Broken:
            async def create(self, **_):
                raise RuntimeError("rate limited")

        class FakeClient:
            def __init__(self, **_):
                self.embeddings = Broken()

        monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "k")
        monkeypatch.setattr(embedding_model, "AsyncOpenAI", FakeClient)
        with pytest.raises(EmbeddingUnavailableError):
            await embedding_model.embed(["text"])

    async def test_wrong_dimension_is_rejected(self, monkeypatch):
        wrong = FakeEmbeddings(dim=384)

        class FakeClient:
            def __init__(self, **_):
                self.embeddings = wrong

        monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "k")
        monkeypatch.setattr(embedding_model, "AsyncOpenAI", FakeClient)
        with pytest.raises(EmbeddingUnavailableError, match="1536"):
            await embedding_model.embed(["text"])


class TestSimilarity:
    def test_identical_vectors_score_one(self):
        v = vec(1.0, 2.0, 3.0)
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors_score_zero(self):
        assert cosine_similarity(vec(1.0, 0.0), vec(0.0, 1.0)) == pytest.approx(0.0)

    def test_direction_matters_not_magnitude(self):
        assert cosine_similarity(vec(1.0, 1.0), vec(10.0, 10.0)) == pytest.approx(1.0)

    def test_zero_vector_returns_zero_rather_than_dividing(self):
        assert cosine_similarity(vec(0.0), vec(1.0, 1.0)) == 0.0

    def test_mismatched_dimensions_raise(self):
        """Same-length vectors from different models describe different
        spaces; different lengths are an outright error."""

        with pytest.raises(DimensionMismatchError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_result_is_bounded(self):
        score = cosine_similarity(vec(0.3, -0.9, 0.1), vec(-0.2, 0.4, 0.8))
        assert -1.0 - 1e-9 <= score <= 1.0 + 1e-9
        assert not math.isnan(score)


class TestRanking:
    def test_orders_best_first(self):
        query = vec(1.0, 0.0)
        results = rank(query, [("far", vec(0.9, 0.4)), ("near", vec(1.0, 0.05))])
        assert [r[0] for r in results] == ["near", "far"]

    def test_irrelevant_candidates_are_dropped(self):
        """Cosine similarity always yields a closest match. Without a floor,
        the retriever hands back the least-irrelevant document and outreach
        cites it as proof."""

        results = rank(vec(1.0, 0.0), [("unrelated", vec(0.0, 1.0))])
        assert results == []

    def test_top_k_is_honoured(self):
        candidates = [(f"c{i}", vec(1.0, i * 0.01)) for i in range(10)]
        assert len(rank(vec(1.0, 0.0), candidates, top_k=3)) == 3

    def test_threshold_helper(self):
        assert is_relevant(RELEVANCE_THRESHOLD)
        assert not is_relevant(RELEVANCE_THRESHOLD - 0.01)


class TestAgentInterface:
    async def test_accepts_a_single_text(self, fake_openai):
        out = await EmbeddingsAgent().run({"text": "hello"})
        assert len(out["vector"]) == EMBEDDING_DIM
        assert out["embedding_model"] == embedding_model.MODEL_NAME

    async def test_accepts_a_batch(self, fake_openai):
        out = await EmbeddingsAgent().run({"texts": ["a", "b", "c"]})
        assert len(out["vectors"]) == 3

    async def test_empty_input_makes_no_call(self, fake_openai):
        out = await EmbeddingsAgent().run({})
        assert out["vectors"] == []
        assert fake_openai.calls == []

    async def test_reports_the_model_identity_to_store_alongside(self, fake_openai):
        """Vectors from different models are not comparable, so every stored
        row records which model produced it."""

        out = await EmbeddingsAgent().run({"text": "x"})
        assert out["dimensions"] == EMBEDDING_DIM
        assert out["model_version"]


class TestRAGGrounding:
    async def test_no_content_falls_back_to_no_verified_proof(self, fake_openai):
        out = await RAGRetriever().run({"query": "case study", "company_id": "abc"})
        assert out["grounded"] is False
        assert out["fallback_note"] == NO_VERIFIED_PROOF

    async def test_missing_company_id_refuses_to_search(self, fake_openai):
        """A missing tenant id must never widen the search across tenants."""

        out = await RAGRetriever().run({"query": "case study"})
        assert out["chunks"] == []
        assert "company_id" in out["reason"]

    async def test_unavailable_embeddings_are_distinguishable_from_no_matches(self, monkeypatch):
        """Otherwise a broken API key silently downgrades a grounded email to
        an ungrounded one with no signal that anything failed."""

        monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "")
        out = await RAGRetriever().run({"query": "case study", "company_id": "abc"})
        assert out["available"] is False
        assert out["grounded"] is False

        # Contrast: embeddings work, we simply have nothing indexed.
        monkeypatch.setattr(embedding_model.settings, "OPENAI_API_KEY", "k")

    async def test_available_true_when_search_ran_but_found_nothing(self, fake_openai):
        out = await RAGRetriever().run({"query": "case study", "company_id": "abc"})
        assert out["available"] is True
        assert out["grounded"] is False
