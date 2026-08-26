from __future__ import annotations
from collections.abc import Iterable
from app.embedding_service.embedder import embed_texts


def batches(items: list[str], size: int = 32) -> Iterable[tuple[int, list[list[float]]]]:
    for offset in range(0, len(items), size):
        yield offset, embed_texts(items[offset:offset + size])
