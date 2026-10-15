"""Ranking metrics with binary relevance, used by `eval/search_eval.py`.

Standard definitions: precision at k (relevant among the first k, divided by k), reciprocal rank
(1 / rank of the first relevant result, 0 if none), and nDCG at k with gain 1 for a relevant
result and the log2(rank + 1) discount, divided by the best possible value for that many
relevant results."""

import math
from collections.abc import Sequence


def precision_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return sum(1 for s in ranked[:k] if s in relevant) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float:
    return next((1.0 / (i + 1) for i, s in enumerate(ranked) if s in relevant), 0.0)


def ndcg_at(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    gain = sum(1.0 / math.log2(i + 2) for i, s in enumerate(ranked[:k]) if s in relevant)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return gain / ideal if ideal else 0.0
