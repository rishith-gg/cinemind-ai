"""Search settings (settings section `[search]`).

Reciprocal Rank Fusion (Cormack, Clarke and Buettcher, SIGIR 2009): every result list adds
weight / (k + rank) to each shot it contains; k = 60 is the value from that paper, not tuned by
us. The CLIP prompt template is the plain one from the CLIP paper ("a photo of a {}.")."""

from typing import Self

from pydantic import BaseModel, model_validator

RETRIEVERS = ("keyword", "labels", "text", "visual")


class SearchConfig(BaseModel):
    rrf_k: int = 60
    # How many items each result list contributes before fusion.
    depth: int = 100
    # How many fused results are returned at most.
    max_results: int = 50
    # Weight of each list in the fusion (1 = plain RRF).
    weights: dict[str, float] = {name: 1.0 for name in RETRIEVERS}
    # Transcript lines less similar than this to the query are left out of the "text" list. Vector
    # search always returns its quota, and unrelated lines would still get a rank and lift their
    # shots in the fusion. 0.35 was chosen on a development set of 12 queries, apart from the
    # 17 test queries (EVALUATION.md section 10, D-086): the lowest value that reached the best
    # nDCG@10 there (0.35 to 0.55 and "off" scored the same; 0.25 lower).
    text_min_similarity: float = 0.35
    # How a typed query is put to the picture model.
    visual_prompt: str = "a photo of {}."

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        if self.rrf_k < 1 or not 1 <= self.depth <= 1000 or not 1 <= self.max_results <= 500:
            raise ValueError("search.rrf_k >= 1, depth 1..1000, max_results 1..500")
        unknown = set(self.weights) - set(RETRIEVERS)
        if unknown or any(w < 0 for w in self.weights.values()):
            raise ValueError(f"search.weights: keys among {RETRIEVERS}, values >= 0")
        if not -1 <= self.text_min_similarity <= 1:
            raise ValueError("search.text_min_similarity must be between -1 and 1")
        if "{}" not in self.visual_prompt:
            raise ValueError("search.visual_prompt must contain {} where the query goes")
        return self
