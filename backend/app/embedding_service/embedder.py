from __future__ import annotations
from time import perf_counter
from app.embedding_service.model_loader import load_embedding_model
from app.monitoring.metrics import EMBEDDING_LATENCY


def embed_texts(texts,is_query=False):
    prepared=[f"Represent this question for retrieving relevant code: {text}" if is_query else text for text in texts]
    started=perf_counter()
    vectors=load_embedding_model().encode(prepared,normalize_embeddings=True,show_progress_bar=False)
    EMBEDDING_LATENCY.observe(perf_counter()-started)
    return vectors.tolist()
