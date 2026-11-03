"""Metrics used to score retrieval runs against a human-reviewed gold set."""


def retrieval_case_metrics(hit_ids, relevant_ids, k):
    relevant = set(relevant_ids)
    ranked = list(hit_ids[:k])
    first_rank = next(
        (rank for rank, hit_id in enumerate(ranked, start=1) if hit_id in relevant),
        None,
    )
    relevant_found = len(set(ranked) & relevant)
    return {
        "recall_at_k": relevant_found / len(relevant) if relevant else 0.0,
        "precision_at_k": relevant_found / k if k else 0.0,
        "reciprocal_rank": 1 / first_rank if first_rank else 0.0,
    }


def aggregate_retrieval_metrics(cases):
    count = len(cases)
    if not count:
        return {"cases": 0, "recall_at_k": 0, "precision_at_k": 0, "mrr": 0}
    return {
        "cases": count,
        "recall_at_k": sum(item["recall_at_k"] for item in cases) / count,
        "precision_at_k": sum(item["precision_at_k"] for item in cases) / count,
        "mrr": sum(item["reciprocal_rank"] for item in cases) / count,
    }
