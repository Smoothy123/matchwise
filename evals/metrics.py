"""Ranking metrics as small pure functions, so each can be checked by hand.

ranked = posting ids in the order a system returned them.

precision@k  Of the first k results, the share that are good matches. What a person
             sees first: k = 5.
recall@k     Of all the good matches we know of, the share found in the first k.
             Shows whether the right jobs survive retrieval and filtering: k = 20.
nDCG@k       Rewards putting better matches higher, using the 0/1/2 grades
             (gain 2^grade - 1, discounted by log2 of the position): k = 10.
violations@k Share of the first k results that break something the person ruled out.
judged@k     Share of the first k results that have a label at all. Unlabelled
             results count as "not a match" in the other metrics (the usual
             pooling assumption), so a low judged@k means those numbers are pessimistic.
"""

import math
import random
import statistics


def precision_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return sum(1 for doc in ranked[:k] if doc in relevant) / k


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float | None:
    """None when the profile has no known good matches: recall isn't defined then."""
    if not relevant:
        return None
    return sum(1 for doc in ranked[:k] if doc in relevant) / len(relevant)


def dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(position + 2) for position, grade in enumerate(grades))


def ndcg_at_k(ranked: list[str], grades: dict[str, int], k: int) -> float | None:
    """DCG of this ranking divided by the DCG of the best possible ranking of the labelled jobs."""
    ideal = dcg(sorted(grades.values(), reverse=True)[:k])
    if ideal == 0:
        return None
    return dcg([grades.get(doc, 0) for doc in ranked[:k]]) / ideal


def rate_at_k(ranked: list[str], flagged: set[str], k: int) -> float:
    """Share of the first k results (of those returned) that are in `flagged`."""
    top = ranked[:k]
    return sum(1 for doc in top if doc in flagged) / len(top) if top else 0.0


def mean_and_ci(values: list[float], resamples: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean over profiles, with a 95% bootstrap interval: resample the profiles with
    replacement many times and take the middle 95% of the resampled means. With only
    ~15 profiles the interval is wide, and it should be."""
    if not values:
        return math.nan, math.nan, math.nan
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(resamples))
    return statistics.fmean(values), means[int(0.025 * resamples)], means[int(0.975 * resamples) - 1]
