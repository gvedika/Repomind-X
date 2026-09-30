"""Embedders for the local code index. BGE on CPU by default; a hashing embedder exists for offline tests only."""
from __future__ import annotations
import hashlib
import re
from typing import Protocol
import numpy as np

QUERY_INSTRUCTION = "Represent this question for retrieving relevant code: "


class Embedder(Protocol):
    name: str
    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Bi-encoder; queries get the configured retrieval instruction (BGE's by default), documents are encoded as-is."""
    def __init__(self, model_name: str | None = None, device: str | None = None, batch_size: int = 32, query_instruction: str | None = None):
        from app.core.config import settings
        self.model_name = model_name or settings.embedding_model
        self.device = device or settings.model_device
        self.batch_size = batch_size
        self.query_instruction = settings.embedding_query_instruction if query_instruction is None else query_instruction
        suffix = hashlib.sha1(self.query_instruction.encode()).hexdigest()[:8] if self.query_instruction != QUERY_INSTRUCTION else ""
        self.name = f"st:{self.model_name}" + (f":{suffix}" if suffix else "")
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self.model_name, device=self.device)
            self._model.max_seq_length = min(self._model.max_seq_length or 512, 512)
        return self._model

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        prepared = [self.query_instruction + t if is_query else t for t in texts]
        vectors = self.model.encode(prepared, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False, convert_to_numpy=True)
        return np.asarray(vectors, dtype=np.float32)


class HashingEmbedder:
    """Deterministic bag-of-tokens hashing vectors. Not a semantic model: used for tests without model downloads."""
    name = "hashing-test"

    def __init__(self, dim: int = 256): self.dim = dim

    def encode(self, texts: list[str], is_query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                out[row, int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)


_default: Embedder | None = None


def default_embedder() -> Embedder:
    global _default
    if _default is None: _default = SentenceTransformerEmbedder()
    return _default
