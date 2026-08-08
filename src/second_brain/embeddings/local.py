"""Dependency-light local semantic hashing embeddings.

This is a rebuildable generated index, not canonical knowledge. It combines token and character
n-gram features into a normalized fixed-size vector. It is intentionally local/offline and gives
useful paraphrase/near-phrase similarity without requiring a heavyweight model download.
"""

from __future__ import annotations

import hashlib
import math
import re

from second_brain.embeddings.base import EmbeddingProvider

TOKEN = re.compile(r"[a-z0-9]+")


class LocalEmbeddingProvider(EmbeddingProvider):
    name = "local-hashing-v1"

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions < 64:
            raise ValueError("Local embedding dimensions must be >= 64")
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        normalized = " ".join(TOKEN.findall(text.lower()))
        tokens = normalized.split()
        features: list[tuple[str, float]] = []
        for token in tokens:
            features.append((f"tok:{token}", 2.0))
        for left, right in zip(tokens, tokens[1:], strict=False):
            features.append((f"bigram:{left}_{right}", 1.5))
        compact = normalized.replace(" ", "_")
        for index in range(max(0, len(compact) - 2)):
            features.append((f"tri:{compact[index:index + 3]}", 0.35))

        for feature, weight in features:
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=16).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dimensions
            sign = 1.0 if digest[8] & 1 else -1.0
            vector[bucket] += sign * weight

        magnitude = math.sqrt(sum(value * value for value in vector))
        if magnitude:
            return [value / magnitude for value in vector]
        return vector


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))
