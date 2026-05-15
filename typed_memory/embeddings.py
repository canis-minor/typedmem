"""Embedding providers.

v0.2 ships a zero-dep ``HashingEmbeddingProvider``. The protocol is small on
purpose so an OpenAI / sentence-transformers provider can drop in for v0.3.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, Protocol


class EmbeddingProvider(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def dim(self) -> int: ...
    def embed(self, texts: Iterable[str]) -> list[list[float]]: ...


_TOKEN = re.compile(r"[a-z0-9]+")


def _ngrams(tokens: list[str], n: int) -> list[str]:
    if len(tokens) < n:
        return tokens[:]
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


class HashingEmbeddingProvider:
    """Feature-hashing embedder over word unigrams + bigrams.

    Trick is the standard `hash(token) % dim` projection; the sign is taken
    from a second hash to keep the expectation unbiased. Vectors are L2-
    normalized so cosine similarity reduces to a dot product."""

    def __init__(self, dim: int = 256, ngram: int = 2) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        if ngram < 1:
            raise ValueError("ngram must be >= 1")
        self._dim = dim
        self._ngram = ngram

    @property
    def id(self) -> str:
        return f"hashing:dim={self._dim};ngram={self._ngram}"

    @property
    def dim(self) -> int:
        return self._dim

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        tokens = _TOKEN.findall(text.lower())
        if not tokens:
            return [0.0] * self._dim
        features: list[str] = []
        for n in range(1, self._ngram + 1):
            features.extend(_ngrams(tokens, n))
        v = [0.0] * self._dim
        for f in features:
            h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self._dim
            sign = 1.0 if (h[4] & 1) else -1.0
            v[idx] += sign
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            return v
        return [x / norm for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    # Both are unit-norm from HashingEmbeddingProvider, but don't assume it.
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
