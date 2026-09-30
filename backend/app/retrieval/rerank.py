"""Bounded CrossEncoder reranking on CPU by default."""
from __future__ import annotations
from typing import Protocol
import numpy as np

RERANK_TEXT_CHARS = 1500


class Reranker(Protocol):
    name: str
    def score(self, query: str, texts: list[str]) -> np.ndarray: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str | None = None, device: str | None = None, batch_size: int = 16):
        from app.core.config import settings
        self.model_name = str(settings.reranker_path) if (model_name is None and settings.reranker_path) else (model_name or settings.reranker_model)
        self.device = device or settings.model_device
        self.batch_size = batch_size
        self.name = f"ce:{self.model_name}"
        self._model = None

    def score(self, query: str, texts: list[str]) -> np.ndarray:
        if not texts: return np.zeros(0, dtype=np.float32)
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(self.model_name, max_length=512, device=self.device)
        pairs = [(query, t[:RERANK_TEXT_CHARS]) for t in texts]
        return np.asarray(self._model.predict(pairs, batch_size=self.batch_size, show_progress_bar=False), dtype=np.float32)


_default: Reranker | None = None


def default_reranker() -> Reranker:
    global _default
    if _default is None: _default = CrossEncoderReranker()
    return _default
