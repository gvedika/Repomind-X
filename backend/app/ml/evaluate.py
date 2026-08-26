from __future__ import annotations
import math


def precision_at_k(relevant:list[str], ranked:list[str], k:int=5)->float:
    top=ranked[:k]
    if not top:return 0.0
    return sum(x in set(relevant) for x in top)/len(top)


def recall_at_k(relevant:list[str], ranked:list[str], k:int=5)->float:
    if not relevant:return 0.0
    return sum(x in set(relevant) for x in ranked[:k])/len(set(relevant))


def mrr(relevant:list[str], ranked:list[str])->float:
    rel=set(relevant)
    for i,x in enumerate(ranked,1):
        if x in rel:return 1.0/i
    return 0.0


def ndcg_at_k(relevant:list[str], ranked:list[str], k:int=5)->float:
    rel=set(relevant); gains=[1 if x in rel else 0 for x in ranked[:k]]
    dcg=sum(g/math.log2(i+2) for i,g in enumerate(gains))
    ideal=sum(1/math.log2(i+2) for i in range(min(k,len(rel))))
    return dcg/ideal if ideal else 0.0


def ranking_metrics(relevant:list[str],ranked:list[str],k:int=5):
    return {"precision_at_k":precision_at_k(relevant,ranked,k),"recall_at_k":recall_at_k(relevant,ranked,k),
            "mrr":mrr(relevant,ranked),"ndcg":ndcg_at_k(relevant,ranked,k)}
