from typed_memory.embeddings import HashingEmbeddingProvider, cosine


def test_dim_matches_output():
    h = HashingEmbeddingProvider(dim=64)
    [v] = h.embed(["hello world"])
    assert len(v) == 64


def test_unit_norm():
    h = HashingEmbeddingProvider()
    [v] = h.embed(["the quick brown fox"])
    s = sum(x * x for x in v) ** 0.5
    assert abs(s - 1.0) < 1e-9


def test_similar_texts_score_higher():
    h = HashingEmbeddingProvider(dim=512)
    a, b, c = h.embed([
        "child said more milk",
        "the child wanted more milk",
        "fixing the kitchen sink",
    ])
    assert cosine(a, b) > cosine(a, c)


def test_empty_text_returns_zero_vec():
    h = HashingEmbeddingProvider(dim=32)
    [v] = h.embed([""])
    assert v == [0.0] * 32


def test_id_changes_with_dim():
    assert HashingEmbeddingProvider(dim=128).id != HashingEmbeddingProvider(dim=256).id
