from __future__ import annotations
import math


def precision_at_k(retrieved:list[str],relevant:set[str],k:int)->float:
    if k<=0:return 0.0
    return sum(x in relevant for x in retrieved[:k])/k


def recall_at_k(retrieved:list[str],relevant:set[str],k:int)->float:
    return sum(x in relevant for x in retrieved[:k])/len(relevant) if relevant else 0.0


def reciprocal_rank(retrieved:list[str],relevant:set[str])->float:
    for i,x in enumerate(retrieved,1):
        if x in relevant:return 1/i
    return 0.0


def ndcg_at_k(retrieved:list[str],relevant:set[str],k:int)->float:
    gains=[1 if x in relevant else 0 for x in retrieved[:k]]
    dcg=sum(g/math.log2(i+2) for i,g in enumerate(gains))
    ideal=sum(1/math.log2(i+2) for i in range(min(k,len(relevant))))
    return dcg/ideal if ideal else 0.0
