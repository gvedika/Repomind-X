from __future__ import annotations
from app.ml.model import load_reranker
from app.services.vector import VectorDocument
from app.monitoring.metrics import RERANKING_LATENCY
from time import perf_counter


def rerank(query,candidates,limit=5):
    if not candidates:return []
    model=load_reranker()
    started=perf_counter(); scores=model.predict([(query,c.text) for c in candidates]); RERANKING_LATENCY.observe(perf_counter()-started)
    ranked=[VectorDocument(id=c.id,text=c.text,metadata=c.metadata,score=float(s)) for c,s in zip(candidates,scores)]
    return sorted(ranked,key=lambda x:x.score,reverse=True)[:limit]
