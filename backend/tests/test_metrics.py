from app.evaluation.metrics import precision_at_k,recall_at_k,reciprocal_rank,ndcg_at_k


def test_ranking_metrics():
    retrieved=["a","b","c","d","e"]; relevant={"b","d"}
    assert precision_at_k(retrieved,relevant,5)==.4
    assert recall_at_k(retrieved,relevant,5)==1.0
    assert reciprocal_rank(retrieved,relevant)==.5
    assert ndcg_at_k(retrieved,relevant,5)>0.0
