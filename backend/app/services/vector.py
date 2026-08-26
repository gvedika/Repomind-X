"""Persistent ChromaDB semantic retrieval backed by BGE embeddings."""
from __future__ import annotations
from dataclasses import dataclass
from time import perf_counter
from chromadb import HttpClient
from app.core.config import settings
from app.embedding_service.embedder import embed_texts
from app.monitoring.metrics import VECTOR_SEARCH_LATENCY


@dataclass(frozen=True)
class VectorDocument:
    id: str
    text: str
    metadata: dict
    score: float = 0.0


class ChromaVectorStore:
    def __init__(self, repository_id: str) -> None:
        if not settings.chroma_host:
            raise RuntimeError("CHROMA_HOST must be configured; in-memory vector retrieval is not supported.")
        self.collection_name = f"repomind_{repository_id}".replace("-", "_")
        self.client = HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        self.collection = self.client.get_or_create_collection(self.collection_name, metadata={"hnsw:space": "cosine"})

    def upsert(self, documents: list[VectorDocument]) -> None:
        if not documents:
            return
        embeddings = embed_texts([item.text for item in documents])
        self.collection.upsert(ids=[item.id for item in documents], documents=[item.text for item in documents], metadatas=[item.metadata for item in documents], embeddings=embeddings)

    def query(self, question: str, limit: int = 50, filters: dict | None = None) -> list[VectorDocument]:
        started = perf_counter()
        response = self.collection.query(query_embeddings=embed_texts([question], is_query=True), n_results=limit, where=filters, include=["documents", "metadatas", "distances"])
        VECTOR_SEARCH_LATENCY.observe(perf_counter() - started)
        documents = response.get("documents", [[]])[0]
        metadata = response.get("metadatas", [[]])[0]
        distances = response.get("distances", [[]])[0]
        return [VectorDocument(id=identifier, text=text or "", metadata=meta or {}, score=1 - float(distance)) for identifier, text, meta, distance in zip(response.get("ids", [[]])[0], documents, metadata, distances)]

    def delete_entity(self, entity_id: str) -> None:
        self.collection.delete(ids=[entity_id])
