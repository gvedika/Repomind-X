"""Per repository+commit code index persisted under <materialized repo>/.repomind/."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
from app.models.schemas import CodeUnit, ParseCoverage
from app.retrieval.documents import document_text, retrieval_units
from app.retrieval.embedding import Embedder
from app.retrieval.graph import CodeGraph, build_code_graph
from app.retrieval.lexical import BM25Index, tokenize, unit_tokens

METADATA_DIR = ".repomind"


@dataclass
class CodeIndex:
    repository_id: str
    commit_sha: str
    root: Path
    units: list[CodeUnit]
    coverage: ParseCoverage | None = None
    texts: list[str] = field(default_factory=list)
    embeddings: np.ndarray | None = None
    embedder_name: str | None = None
    indexed_at: str = ""

    def __post_init__(self):
        self.all_units = [u for u in self.units if u.repository_id == self.repository_id and u.commit_sha == self.commit_sha]
        self.units = retrieval_units(self.all_units)
        self._graph = None
        self.texts = [document_text(u) for u in self.units]
        self.by_id = {u.unit_id: u for u in self.units}
        self.position = {u.unit_id: i for i, u in enumerate(self.units)}
        self._lexical = None

    @property
    def graph(self) -> CodeGraph:
        if self._graph is None: self._graph = build_code_graph(self.all_units)
        return self._graph

    # -- persistence ---------------------------------------------------------------------------------------
    @classmethod
    def load(cls, root: Path) -> "CodeIndex":
        meta = root / METADATA_DIR
        summary = json.loads((meta / "summary.json").read_text(encoding="utf-8"))
        units = [CodeUnit.model_validate_json(line) for line in (meta / "units.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        coverage = ParseCoverage.model_validate(summary["parse_coverage"]) if summary.get("parse_coverage") else None
        return cls(summary["id"], summary.get("commit_sha", "worktree"), root, units, coverage, indexed_at=summary.get("indexed_at", ""))

    def _embedding_path(self) -> Path:
        return self.root / METADATA_DIR / "embeddings.npz"

    def ensure_embeddings(self, embedder: Embedder) -> None:
        """Reuse cached vectors only when the model and the exact unit-ID list match."""
        if self.embeddings is not None and self.embedder_name == embedder.name: return
        path = self._embedding_path()
        ids = np.array([u.unit_id for u in self.units])
        if path.exists():
            cached = np.load(path, allow_pickle=False)
            if str(cached["model"]) == embedder.name and cached["ids"].tolist() == ids.tolist():
                self.embeddings, self.embedder_name = cached["vectors"], embedder.name
                return
        vectors = embedder.encode(self.texts) if self.texts else np.zeros((0, 1), dtype=np.float32)
        self.embeddings, self.embedder_name = np.asarray(vectors, dtype=np.float32), embedder.name
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, ids=ids, vectors=self.embeddings, model=np.array(embedder.name))

    # -- retrieval -----------------------------------------------------------------------------------------
    def _mask(self, language: str | None) -> np.ndarray:
        if not language: return np.ones(len(self.units), dtype=bool)
        return np.array([u.language.lower() == language.lower() for u in self.units], dtype=bool)

    def semantic(self, query: str, embedder: Embedder, limit: int, language: str | None = None) -> list[tuple[str, float]]:
        if not self.units: return []
        self.ensure_embeddings(embedder)
        q = embedder.encode([query], is_query=True)[0]
        scores = self.embeddings @ q
        scores = np.where(self._mask(language), scores, -np.inf)
        order = np.argsort(-scores, kind="stable")[:limit]
        return [(self.units[i].unit_id, float(scores[i])) for i in order if np.isfinite(scores[i])]

    def lexical(self, query: str, limit: int, language: str | None = None) -> list[tuple[str, float]]:
        if not self.units: return []
        if self._lexical is None: self._lexical = BM25Index([unit_tokens(u) for u in self.units])
        mask = self._mask(language)
        scored = [(i, s) for i, s in self._lexical.scores(tokenize(query)).items() if mask[i] and s > 0]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return [(self.units[i].unit_id, float(s)) for i, s in scored[:limit]]
