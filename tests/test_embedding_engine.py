import numpy as np
import pytest

from src.code_memory.embedding_engine import EmbeddingEngine


@pytest.fixture
def engine(tmp_path):
    return EmbeddingEngine(model_dir=str(tmp_path / "models"))


class TestModelLoading:
    def test_engine_initializes(self, engine):
        assert engine is not None
        assert not engine.is_ready

    def test_engine_loads_model(self, engine):
        engine.ensure_ready()
        assert engine.is_ready


class TestEmbedding:
    def test_embed_returns_384_dim_vector(self, engine):
        engine.ensure_ready()
        vec = engine.embed("hello world")
        assert vec.shape == (384,)
        assert vec.dtype == np.float32

    def test_embed_is_normalized(self, engine):
        engine.ensure_ready()
        vec = engine.embed("test sentence")
        norm = np.linalg.norm(vec)
        assert abs(norm - 1.0) < 1e-5

    def test_embed_batch(self, engine):
        engine.ensure_ready()
        vecs = engine.embed_batch(["hello", "world", "test"])
        assert vecs.shape == (3, 384)

    def test_embed_batch_empty(self, engine):
        engine.ensure_ready()
        vecs = engine.embed_batch([])
        assert vecs.shape == (0, 384)

    def test_similar_texts_have_high_similarity(self, engine):
        engine.ensure_ready()
        v1 = engine.embed("Product class for e-commerce")
        v2 = engine.embed("Product model in the shop")
        v3 = engine.embed("completely unrelated weather forecast")
        sim_related = EmbeddingEngine.cosine_similarity(v1, v2.reshape(1, -1))[0]
        sim_unrelated = EmbeddingEngine.cosine_similarity(v1, v3.reshape(1, -1))[0]
        assert sim_related > sim_unrelated

    def test_word_order_invariance(self, engine):
        engine.ensure_ready()
        v1 = engine.embed("Product Origin relationship")
        v2 = engine.embed("Origin Product relationship")
        sim = EmbeddingEngine.cosine_similarity(v1, v2.reshape(1, -1))[0]
        assert sim > 0.85


class TestSerialization:
    def test_vector_roundtrip(self, engine):
        engine.ensure_ready()
        vec = engine.embed("test")
        blob = EmbeddingEngine.vector_to_blob(vec)
        restored = EmbeddingEngine.blob_to_vector(blob)
        np.testing.assert_array_almost_equal(vec, restored)
