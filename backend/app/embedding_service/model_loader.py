from __future__ import annotations
from functools import lru_cache
from sentence_transformers import SentenceTransformer
from app.core.config import settings


@lru_cache(maxsize=1)
def load_embedding_model() -> SentenceTransformer:
    """Load BGE once per worker; model weights are fetched and cached by Hugging Face."""
    return SentenceTransformer(settings.embedding_model, device=settings.model_device)
