from src.search.evaluation import evaluate, recall_at_k, reciprocal_rank


def test_recall_and_mrr_metrics():
    assert recall_at_k({"r1"}, ["r2", "r1"], 2) == 1.0
    assert reciprocal_rank({"r1"}, ["r2", "r1"]) == 0.5
