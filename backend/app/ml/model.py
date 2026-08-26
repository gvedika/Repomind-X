from __future__ import annotations
from functools import lru_cache
from sentence_transformers import CrossEncoder
from app.core.config import settings


@lru_cache(maxsize=1)
def load_reranker():
    model_name=str(settings.reranker_path) if settings.reranker_path else settings.reranker_model
    return CrossEncoder(model_name,max_length=512)
