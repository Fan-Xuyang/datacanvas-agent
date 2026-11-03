import pytest

from app.evaluation import aggregate_retrieval_metrics, retrieval_case_metrics


def test_retrieval_metrics_use_recall_precision_and_first_relevant_rank():
    metrics = retrieval_case_metrics(
        ["irrelevant", "gold-a", "gold-b"], ["gold-a", "gold-b", "missing"], 2
    )
    assert metrics == {
        "recall_at_k": pytest.approx(1 / 3),
        "precision_at_k": pytest.approx(1 / 2),
        "reciprocal_rank": pytest.approx(1 / 2),
    }
    assert aggregate_retrieval_metrics([metrics])["mrr"] == pytest.approx(1 / 2)
