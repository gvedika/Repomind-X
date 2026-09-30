from pathlib import Path
import numpy as np
import pytest
from app.core.config import settings
from app.models.schemas import IngestRequest, RetrievalMode, SearchRequest, SearchResult
from app.retrieval.embedding import HashingEmbedder
from app.retrieval.lexical import tokenize
from app.retrieval.service import reciprocal_rank_fusion, registry, search

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_js_repo"


class CountingReranker:
    """Deterministic stand-in for the CrossEncoder: scores by overlap and records pool sizes."""
    name, device = "fake-reranker", "cpu"

    def __init__(self): self.calls = []

    def score(self, query, texts):
        self.calls.append(len(texts))
        q = set(tokenize(query))
        return np.array([len(q & set(tokenize(t))) for t in texts], dtype=np.float32)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    from app.services import ingestion
    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", None)
    embedder = HashingEmbedder()
    summary = ingestion.ingest(IngestRequest(source=str(SAMPLE)), embedder=embedder)
    yield summary, embedder
    registry._items.clear()


def test_rrf_deduplicates_and_orders():
    fused = reciprocal_rank_fusion({"a": [("x", 9.0), ("y", 5.0)], "b": [("y", 0.9), ("z", 0.8), ("x", 0.1)]}, k=60)
    ids = [u for u, _ in fused]
    assert ids == ["y", "x", "z"] and len(ids) == len(set(ids))
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_lexical_matches_split_identifiers(repo):
    summary, embedder = repo
    top = search(SearchRequest(repository_id=summary.id, query="purge expired sessions", mode="lexical", top_k=3), embedder).results[0]
    assert top.qualified_name == "SessionManager.purgeExpired" and top.evidence == ["lexical"]
    assert top.component_ranks == {"lexical": 1}


@pytest.mark.parametrize("mode", [RetrievalMode.SEMANTIC, RetrievalMode.LEXICAL, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK])
def test_all_modes_return_same_canonical_result_type(repo, mode):
    summary, embedder = repo
    response = search(SearchRequest(repository_id=summary.id, query="retry failed operation with backoff", mode=mode, top_k=5), embedder, CountingReranker())
    assert response.mode == mode and 1 <= len(response.results) <= 5
    for result in response.results:
        assert isinstance(result, SearchResult) and result.unit_id.startswith("cu_") and result.line_start >= 1
    ids = [r.unit_id for r in response.results]
    assert len(ids) == len(set(ids))
    assert [r.rank for r in response.results] == list(range(1, len(ids) + 1))


def test_hybrid_exposes_component_scores_and_ranks(repo):
    summary, embedder = repo
    response = search(SearchRequest(repository_id=summary.id, query="constant time digest comparison", mode="hybrid", top_k=5), embedder)
    assert [t.action for t in response.trace] == ["lexical", "semantic", "rrf"] and response.tool_calls == 3
    top = response.results[0]
    assert top.qualified_name == "safeEqual"
    assert {"lexical", "semantic", "rrf"} <= set(top.score_components) and {"lexical", "semantic"} <= set(top.component_ranks)
    assert top.score == pytest.approx(top.score_components["rrf"])
    assert top.evidence == ["lexical", "semantic"]


def test_rerank_is_bounded_and_recorded(repo, monkeypatch):
    summary, embedder = repo
    monkeypatch.setattr(settings, "rerank_candidates", 4)
    reranker = CountingReranker()
    response = search(SearchRequest(repository_id=summary.id, query="charge the card through the payment gateway", mode="hybrid_rerank", top_k=3), embedder, reranker)
    assert reranker.calls == [4] and response.trace[-1].action == "reranker" and response.trace[-1].candidates == 4
    assert all("reranker" in r.score_components and "reranker" in r.evidence for r in response.results)


def test_language_filter_scopes_results(repo, tmp_path):
    summary, embedder = repo
    assert search(SearchRequest(repository_id=summary.id, query="retry backoff", mode="hybrid", language="Python"), embedder).results == []
    assert all(r.language == "JavaScript" for r in search(SearchRequest(repository_id=summary.id, query="retry backoff", mode="hybrid", language="javascript"), embedder).results)


def test_cpu_and_budget_defaults():
    assert settings.model_device == "cpu"
    assert 0 < settings.rerank_candidates <= settings.retrieval_candidates <= 200
    assert SearchRequest(repository_id="r", query="abc").mode == RetrievalMode.HYBRID
    with pytest.raises(Exception): SearchRequest(repository_id="r", query="abc", top_k=500)


def test_dev_labels_resolve_to_units(repo):
    import json
    from app.evaluation.retrieval_eval import evaluate
    summary, embedder = repo
    dataset = json.loads((Path(__file__).resolve().parents[1] / "evaluation" / "dev_sample_js.json").read_text(encoding="utf-8"))
    report = evaluate(summary.id, dataset, [RetrievalMode.LEXICAL], embedder=embedder)
    assert report["queries"] == 18 and report["split"] == "dev" and 0 <= report["modes"]["lexical"]["mrr@10"] <= 1
