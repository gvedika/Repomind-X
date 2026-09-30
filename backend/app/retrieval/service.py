"""Retrieval service: repository/commit scoped search that returns ranked, source-verified code units."""
from __future__ import annotations
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from app.core.config import settings
from app.models.schemas import RetrievalMode, SearchRequest, SearchResponse, SearchResult, SourceStatus, TraceStep
from app.retrieval.adaptive import adaptive_search
from app.retrieval.embedding import Embedder, default_embedder
from app.retrieval.index import METADATA_DIR, CodeIndex
from app.retrieval.rerank import Reranker, default_reranker
from app.retrieval.source import verify_source


class IndexNotFound(LookupError):
    pass


class IndexRegistry:
    """Caches loaded indexes keyed by (repository_id, commit_sha); results never mix repositories or commits."""
    def __init__(self):
        self._items: dict[tuple[str, str], CodeIndex] = {}
        self._lock = threading.Lock()

    def register(self, index: CodeIndex) -> None:
        with self._lock: self._items[(index.repository_id, index.commit_sha)] = index

    def forget(self, repository_id: str, commit_sha: str | None = None) -> None:
        with self._lock:
            for key in [k for k in self._items if k[0] == repository_id and (commit_sha is None or k[1] == commit_sha)]:
                self._items.pop(key)

    def _discover(self, repository_id: str) -> list[CodeIndex]:
        root = Path(settings.repository_root)
        found = []
        for summary in root.glob(f"*/{METADATA_DIR}/summary.json") if root.exists() else []:
            try: data = json.loads(summary.read_text(encoding="utf-8"))
            except (OSError, ValueError): continue
            if data.get("id") == repository_id and (summary.parent / "units.jsonl").exists():
                try: found.append(CodeIndex.load(summary.parent.parent))
                except (OSError, ValueError, KeyError): continue
        return found

    def get(self, repository_id: str, commit_sha: str | None = None) -> CodeIndex:
        with self._lock:
            matches = [v for k, v in self._items.items() if k[0] == repository_id and (commit_sha is None or k[1] == commit_sha)]
        if not matches:
            for index in self._discover(repository_id): self.register(index)
            with self._lock:
                matches = [v for k, v in self._items.items() if k[0] == repository_id and (commit_sha is None or k[1] == commit_sha)]
        if not matches:
            detail = f" at commit {commit_sha}" if commit_sha else ""
            raise IndexNotFound(f"Repository {repository_id}{detail} is not indexed. Ingest it first.")
        return max(matches, key=lambda index: index.indexed_at)

    def commits(self, repository_id: str) -> list[str]:
        with self._lock: return [k[1] for k in self._items if k[0] == repository_id]


registry = IndexRegistry()


def build_results(index: CodeIndex, ranked: list[tuple[str, float]], top_k: int, components: dict[str, dict[str, float]] | None = None,
                  ranks: dict[str, dict[str, int]] | None = None, evidence: dict[str, list[str]] | None = None,
                  relationships: dict[str, list[dict]] | None = None) -> tuple[list[SearchResult], list[str]]:
    """Verify each candidate's source before returning it; invalid/missing units are dropped with a warning."""
    results, warnings = [], []
    for unit_id, score in ranked:
        if len(results) >= top_k: break
        unit = index.by_id.get(unit_id)
        if unit is None:
            warnings.append(f"dropped unknown unit id {unit_id}"); continue
        check = verify_source(index.root, unit, index.repository_id, index.commit_sha)
        if check.status in {SourceStatus.INVALID, SourceStatus.MISSING}:
            warnings.append(f"dropped {unit.qualified_name}: {'; '.join(check.warnings)}"); continue
        results.append(SearchResult(rank=len(results) + 1, unit_id=unit.unit_id, name=unit.name, qualified_name=unit.qualified_name,
            unit_type=unit.unit_type, language=unit.language, signature=unit.signature, file_path=unit.file_path,
            line_start=unit.line_start, line_end=unit.line_end, excerpt=check.excerpt, excerpt_line_end=check.excerpt_line_end,
            excerpt_truncated=check.truncated, source_status=check.status, score=round(float(score), 6),
            score_components={k: round(v, 6) for k, v in (components or {}).get(unit_id, {}).items()},
            component_ranks=(ranks or {}).get(unit_id, {}), evidence=(evidence or {}).get(unit_id, []),
            relationships=(relationships or {}).get(unit_id, [])[:8],
            warnings=[*check.warnings, *unit.parser_uncertainty]))
    return results, warnings


def _coverage_warnings(index: CodeIndex) -> list[str]:
    coverage = index.coverage
    if coverage is None: return []
    notes = []
    if coverage.files_failed or coverage.files_partial:
        notes.append(f"partial parse coverage: {coverage.files_failed} failed and {coverage.files_partial} partially parsed file(s)")
    if coverage.files_skipped:
        notes.append(f"{coverage.files_skipped} file(s) skipped: {coverage.skipped_reasons}")
    return notes


Ranked = list[tuple[str, float]]


TIE_BREAK_ORDER = ("semantic", "reranker", "graph", "lexical")   # semantic was the strongest single signal on the dev split


def reciprocal_rank_fusion(lists: dict[str, Ranked], k: int) -> Ranked:
    """RRF over component rankings; each unit ID appears once.

    Exact score ties (e.g. #1 in one list and #2 in the other, both ways) are broken by best component rank, then
    by rank in the preferred component (TIE_BREAK_ORDER), and only last by unit ID, so the order never depends on
    commit-hashed identifiers."""
    fused: dict[str, float] = {}
    best: dict[str, int] = {}
    ranks: dict[str, dict[str, int]] = {}
    for name, ranked in lists.items():
        for rank, (unit_id, _) in enumerate(ranked, 1):
            fused[unit_id] = fused.get(unit_id, 0.0) + 1.0 / (k + rank)
            best[unit_id] = min(best.get(unit_id, rank), rank)
            ranks.setdefault(unit_id, {})[name] = rank
    preferred = [n for n in TIE_BREAK_ORDER if n in lists] + [n for n in lists if n not in TIE_BREAK_ORDER]
    missing = 10**9
    return sorted(fused.items(), key=lambda item: (-round(item[1], 12), best[item[0]],
                                                   *[ranks[item[0]].get(n, missing) for n in preferred], item[0]))


@dataclass
class Pipeline:
    """Bounded single-pass pipeline shared by every non-adaptive mode (and by the adaptive loop's actions)."""
    index: CodeIndex
    embedder: Embedder
    reranker: Reranker | None = None
    language: str | None = None
    components: dict[str, dict[str, float]] = field(default_factory=dict)
    ranks: dict[str, dict[str, int]] = field(default_factory=dict)
    trace: list[TraceStep] = field(default_factory=list)
    tool_calls: int = 0

    def _record(self, name: str, ranked: Ranked, reason: str, started: float, seen: set[str] | None = None) -> Ranked:
        for rank, (unit_id, score) in enumerate(ranked, 1):
            self.components.setdefault(unit_id, {})[name] = score
            self.ranks.setdefault(unit_id, {})[name] = rank
        new = len({u for u, _ in ranked} - seen) if seen is not None else len(ranked)
        self.tool_calls += 1
        self.trace.append(TraceStep(iteration=len(self.trace) + 1, action=name, reason=reason, candidates=len(ranked), new_candidates=new,
                                    duration_ms=round((perf_counter() - started) * 1000, 2)))
        return ranked

    def semantic(self, query: str, limit: int, reason: str = "dense BGE retrieval", seen=None, name: str = "semantic") -> Ranked:
        started = perf_counter()
        return self._record(name, self.index.semantic(query, self.embedder, limit, self.language), reason, started, seen)

    def lexical(self, query: str, limit: int, reason: str = "code-aware BM25 over names, signatures, docstrings and bodies", seen=None) -> Ranked:
        started = perf_counter()
        return self._record("lexical", self.index.lexical(query, limit, self.language), reason, started, seen)

    def fuse(self, lists: dict[str, Ranked]) -> Ranked:
        started = perf_counter()
        fused = reciprocal_rank_fusion(lists, settings.rrf_k)
        return self._record("rrf", fused, f"reciprocal rank fusion (k={settings.rrf_k}) of {', '.join(lists)}", started)

    def rerank(self, query: str, ranked: Ranked, pool: int) -> Ranked:
        started = perf_counter()
        candidates = ranked[:pool]
        reranker = self.reranker or default_reranker()
        scores = reranker.score(query, [self.index.texts[self.index.position[u]] for u, _ in candidates])
        rescored = sorted(zip((u for u, _ in candidates), (float(x) for x in scores)), key=lambda item: -item[1])
        if settings.rerank_fusion == "rrf":   # blend reranker order with first-stage order instead of replacing it
            rescored = reciprocal_rank_fusion({"reranker": rescored, "first_stage": candidates}, settings.rrf_k)
        return self._record("reranker", rescored, f"CrossEncoder rerank of top {len(candidates)} fused candidates on {getattr(reranker, 'device', 'cpu')}", started)


def run_mode(pipeline: Pipeline, query: str, mode: RetrievalMode, top_k: int) -> Ranked:
    limit = max(settings.retrieval_candidates, top_k)
    if mode == RetrievalMode.SEMANTIC: return pipeline.semantic(query, limit)
    if mode == RetrievalMode.LEXICAL: return pipeline.lexical(query, limit)
    if mode == RetrievalMode.ADAPTIVE:
        raise ValueError("adaptive mode is run through adaptive_search")
    fused = pipeline.fuse({"lexical": pipeline.lexical(query, limit), "semantic": pipeline.semantic(query, limit)})
    if mode == RetrievalMode.HYBRID: return fused
    if mode == RetrievalMode.HYBRID_RERANK: return pipeline.rerank(query, fused, max(settings.rerank_candidates, top_k))
    raise ValueError(f"unsupported retrieval mode {mode}")


def _evidence(components: dict[str, float]) -> list[str]:
    labels = {"lexical": "lexical", "semantic": "semantic", "semantic_rewrite": "semantic", "reranker": "reranker",
              "graph": "graph", "structural": "graph"}
    return list(dict.fromkeys(label for key, label in labels.items() if key in components))


def search(request: SearchRequest, embedder: Embedder | None = None, reranker: Reranker | None = None) -> SearchResponse:
    started = perf_counter()
    index = registry.get(request.repository_id, request.commit_sha)
    pipeline = Pipeline(index, embedder or default_embedder(), reranker, request.language)
    relationships, iterations, stop_reason, notes = {}, 1, "single_pass", []
    if request.mode == RetrievalMode.ADAPTIVE:
        outcome = adaptive_search(pipeline, request.query, request.top_k)
        ranked, relationships, iterations, stop_reason = outcome.ranked, outcome.relationships, outcome.iterations, outcome.stop_reason
        if outcome.structural:
            notes.append("call order is syntactic source order within each unit; it does not prove runtime execution order")
    else:
        ranked = run_mode(pipeline, request.query, request.mode, request.top_k)
    for uid, items in list(relationships.items()):
        unresolved = index.graph.unresolved.get(uid, [])
        if unresolved: relationships[uid] = [*items, {"type": "UNRESOLVED_CALLS", "count": len(unresolved), "examples": unresolved[:3]}]
    evidence = {uid: _evidence(c) for uid, c in pipeline.components.items()}
    results, warnings = build_results(index, ranked, request.top_k, pipeline.components, pipeline.ranks, evidence, relationships)
    if not results: warnings.append("no matching code units")
    return SearchResponse(query=request.query, repository_id=index.repository_id, commit_sha=index.commit_sha, mode=request.mode,
                          results=results, trace=pipeline.trace, latency_ms=round((perf_counter() - started) * 1000, 2),
                          iterations=iterations, tool_calls=pipeline.tool_calls, stop_reason=stop_reason,
                          warnings=[*_coverage_warnings(index), *notes, *warnings], parse_coverage=index.coverage)
