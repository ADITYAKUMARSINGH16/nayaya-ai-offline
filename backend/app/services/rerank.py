"""Cheap, model-free reranking utilities.

- `bm25_search` — in-memory BM25 over a small candidate pool. Catches exact
  keyword matches the vector store misses ("section 351", "house trespass").
- `rrf_merge` — Reciprocal Rank Fusion of multiple ranked lists. No ML, pure
  algorithm. Great when you have several weak rankers (vector + BM25 + graph).
"""
from __future__ import annotations

import re
from typing import Hashable, Iterable, Sequence

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:  # pragma: no cover — soft dep
    BM25Okapi = None

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def bm25_search(
    corpus: Sequence[str],
    query: str,
    *,
    top_k: int = 8,
) -> list[tuple[int, float]]:
    """Score `corpus` against `query` with BM25. Returns [(index, score), …]."""
    if not corpus or BM25Okapi is None:
        return []
    tokenised = [tokenize(doc) for doc in corpus]
    if not any(tokenised):
        return []
    bm25 = BM25Okapi(tokenised)
    scores = bm25.get_scores(tokenize(query))
    ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
    return [(i, float(s)) for i, s in ranked[:top_k] if s > 0]


def rrf_merge(
    ranked_lists: Iterable[Sequence[Hashable]],
    *,
    k: int = 60,
    top_k: int = 10,
) -> list[Hashable]:
    """Merge any number of ranked id-lists with Reciprocal Rank Fusion.

    Each list is in best-first order. RRF score for an id = sum(1 / (k + rank))
    across every list it appears in. Higher = better.
    """
    scores: dict[Hashable, float] = {}
    for ranked in ranked_lists:
        for rank, item in enumerate(ranked):
            if item is None:
                continue
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
    ordered = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [item for item, _ in ordered[:top_k]]
