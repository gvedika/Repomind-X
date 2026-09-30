"""Retrieval service: repository/commit scoped search that returns ranked, source-verified code units."""
from __future__ import annotations
import json
import threading
from pathlib import Path
from time import perf_counter
from app.core.config import settings
from app.models.schemas import RetrievalMode, SearchRequest, SearchResponse, SearchResult, SourceStatus, TraceStep
from app.retrieval.embedding import Embedder, default_embedder
from app.retrieval.index import METADATA_DIR, CodeIndex
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
                found.append(CodeIndex.load(summary.parent.parent))
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
        return matches[-1]


registry = IndexRegistry()


def build_results(index: CodeIndex, ranked: list[tuple[str, float]], top_k: int, components: dict[str, dict[str, float]] | None = None,
                  ranks: dict[str, dict[str, int]] | None = None, evidence: dict[str, list[str]] | None = None) -> tuple[list[SearchResult], list[str]]:
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


def search(request: SearchRequest, embedder: Embedder | None = None) -> SearchResponse:
    started = perf_counter()
    index = registry.get(request.repository_id, request.commit_sha)
    embedder = embedder or default_embedder()
    limit = max(settings.retrieval_candidates, request.top_k)
    step_started = perf_counter()
    if request.mode != RetrievalMode.SEMANTIC:
        raise ValueError(f"retrieval mode {request.mode} is not available yet")
    ranked = index.semantic(request.query, embedder, limit, request.language)
    components = {uid: {"semantic": s} for uid, s in ranked}
    ranks = {uid: {"semantic": i + 1} for i, (uid, _) in enumerate(ranked)}
    evidence = {uid: ["semantic"] for uid, _ in ranked}
    trace = [TraceStep(iteration=1, action="semantic_search", reason="single-pass semantic retrieval", candidates=len(ranked),
                       new_candidates=len(ranked), duration_ms=round((perf_counter() - step_started) * 1000, 2))]
    results, warnings = build_results(index, ranked, request.top_k, components, ranks, evidence)
    if not results: warnings.append("no matching code units")
    return SearchResponse(query=request.query, repository_id=index.repository_id, commit_sha=index.commit_sha, mode=request.mode,
                          results=results, trace=trace, latency_ms=round((perf_counter() - started) * 1000, 2),
                          warnings=[*_coverage_warnings(index), *warnings], parse_coverage=index.coverage)
