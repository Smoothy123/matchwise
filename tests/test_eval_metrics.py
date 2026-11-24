import math

import pytest

from evals.metrics import dcg, mean_and_ci, ndcg_at_k, precision_at_k, rate_at_k, recall_at_k

RANKED = ["a", "b", "c", "d", "e"]


def test_precision():
    assert precision_at_k(RANKED, {"a", "c", "z"}, 5) == 2 / 5
    assert precision_at_k(["a"], {"a"}, 5) == 1 / 5   # fewer than k results: the gaps count as misses


def test_recall():
    assert recall_at_k(RANKED, {"a", "c", "z"}, 5) == 2 / 3
    assert recall_at_k(RANKED, {"a", "c", "z"}, 2) == 1 / 3
    assert recall_at_k(RANKED, set(), 5) is None


def test_dcg_by_hand():
    # grade 2 at position 1: (2^2-1)/log2(2) = 3; grade 1 at position 3: (2^1-1)/log2(4) = 0.5
    assert dcg([2, 0, 1]) == pytest.approx(3.5)


def test_ndcg():
    grades = {"a": 0, "b": 2, "c": 1}
    # ideal order is b, c, a -> dcg([2, 1, 0]) = 3 + 1/log2(3)
    assert ndcg_at_k(["b", "c", "a"], grades, 3) == pytest.approx(1.0)
    assert ndcg_at_k(["a", "b", "c"], grades, 3) == pytest.approx(
        (3 / math.log2(3) + 1 / 2) / (3 + 1 / math.log2(3)))
    assert ndcg_at_k(["x", "y"], {"x": 0}, 2) is None          # nothing good to find
    assert ndcg_at_k(["x", "b"], grades, 2) < ndcg_at_k(["b", "x"], grades, 2)  # higher is better


def test_rate():
    assert rate_at_k(RANKED, {"b"}, 10) == 1 / 5     # over the results actually returned
    assert rate_at_k([], {"b"}, 10) == 0.0


def test_mean_and_ci():
    mean, low, high = mean_and_ci([0.0, 0.5, 1.0] * 5)
    assert mean == pytest.approx(0.5)
    assert low < mean < high
    assert mean_and_ci([0.3] * 10) == pytest.approx((0.3, 0.3, 0.3))
    assert all(math.isnan(x) for x in mean_and_ci([]))
