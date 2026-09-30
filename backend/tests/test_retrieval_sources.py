from pathlib import Path
import pytest
from app.models.schemas import IngestRequest, SearchRequest, SourceStatus, UnitType
from app.retrieval.documents import document_text, retrieval_units
from app.retrieval.embedding import HashingEmbedder
from app.retrieval.service import IndexNotFound, registry, search
from app.retrieval.source import verify_source
from app.services.code_units import split_lines

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_js_repo"


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import ingestion
    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", None)
    embedder = HashingEmbedder()

    def run(source=SAMPLE):
        summary = ingestion.ingest(IngestRequest(source=str(source)), embedder=embedder)
        return summary, registry.get(summary.id)
    yield run, embedder
    registry._items.clear()


def test_documents_contain_implementation_bodies(indexed):
    run, _ = indexed
    _, index = run()
    login = next(u for u in index.units if u.qualified_name == "login")
    text = document_text(login)
    assert "crypto.randomBytes(32)" in text and login.signature in text and "src/services/auth.js" in text
    assert all(u.unit_type != UnitType.FILE for u in index.units)   # every sample file has finer units


def test_behavioral_query_returns_verified_snippet_with_exact_span(indexed):
    run, embedder = indexed
    summary, index = run()
    response = search(SearchRequest(repository_id=summary.id, query="exponential backoff sleep between attempts", mode="semantic", top_k=3), embedder)
    top = response.results[0]
    assert top.qualified_name == "withRetry" and top.file_path == "src/utils/retry.cjs"
    assert (top.line_start, top.line_end) == (6, 17) and top.source_status == SourceStatus.VERIFIED
    lines = split_lines((SAMPLE / top.file_path).read_text(encoding="utf-8"))
    assert top.excerpt == "\n".join(lines[5:17]) and top.excerpt_line_end == 17 and not top.excerpt_truncated
    assert response.commit_sha == summary.commit_sha and response.repository_id == summary.id
    assert [r.rank for r in response.results] == [1, 2, 3] and response.trace[0].action == "semantic"


def test_long_units_are_truncated_but_keep_full_span(indexed, tmp_path):
    repo = tmp_path / "long"
    repo.mkdir()
    body = "\n".join(f"  step{i}();" for i in range(120))
    (repo / "long.js").write_text(f"function longTask() {{\n{body}\n}}\n", encoding="utf-8")
    run, embedder = indexed
    summary, index = run(repo)
    result = search(SearchRequest(repository_id=summary.id, query="longTask steps", mode="semantic", top_k=1), embedder).results[0]
    assert (result.line_start, result.line_end) == (1, 122)
    assert result.excerpt_truncated and result.excerpt_line_end == 60 and len(result.excerpt.split("\n")) == 60


def test_verify_source_rejects_invalid_missing_and_stale(indexed):
    run, _ = indexed
    summary, index = run()
    unit = next(u for u in index.units if u.qualified_name == "chunk")
    ok = verify_source(index.root, unit, summary.id, summary.commit_sha)
    assert ok.status == SourceStatus.VERIFIED and ok.excerpt.startswith("function chunk(items, size)")
    assert verify_source(index.root, unit, "other-repo", summary.commit_sha).status == SourceStatus.INVALID
    assert verify_source(index.root, unit, summary.id, "0" * 40).status == SourceStatus.INVALID
    for bad in ("../../etc/passwd", "/etc/passwd", "src/../../x.js"):
        assert verify_source(index.root, unit.model_copy(update={"file_path": bad}), summary.id, summary.commit_sha).status == SourceStatus.INVALID
    missing = verify_source(index.root, unit.model_copy(update={"file_path": "src/nope.js"}), summary.id, summary.commit_sha)
    assert missing.status == SourceStatus.MISSING and missing.excerpt == ""
    out_of_range = verify_source(index.root, unit.model_copy(update={"line_start": 400, "line_end": 410}), summary.id, summary.commit_sha)
    assert out_of_range.status == SourceStatus.STALE and out_of_range.excerpt == ""
    # Edit the materialized snapshot: the span no longer matches what was indexed.
    path = index.root / unit.file_path
    path.write_text(path.read_text(encoding="utf-8").replace("out.push", "result.push"), encoding="utf-8")
    stale = verify_source(index.root, unit, summary.id, summary.commit_sha)
    assert stale.status == SourceStatus.STALE and "out.push" in stale.excerpt and stale.warnings


def test_missing_files_are_dropped_from_results_with_warning(indexed):
    run, embedder = indexed
    summary, index = run()
    (index.root / "src/utils/retry.cjs").unlink()
    response = search(SearchRequest(repository_id=summary.id, query="retry with backoff attempts", mode="semantic", top_k=5), embedder)
    assert all(r.file_path != "src/utils/retry.cjs" for r in response.results)
    assert any("missing" in w for w in response.warnings)


def test_repository_and_commit_isolation(indexed, tmp_path):
    run, embedder = indexed
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.js").write_text("export function retryForever(op) { while (true) op(); }\n", encoding="utf-8")
    first, _ = run()
    second, _ = run(other)
    assert first.id != second.id
    results = search(SearchRequest(repository_id=second.id, query="retry backoff", mode="semantic", top_k=10), embedder).results
    assert {r.file_path for r in results} == {"x.js"}
    with pytest.raises(IndexNotFound):
        search(SearchRequest(repository_id=first.id, query="retry backoff", mode="semantic", commit_sha="deadbeef"), embedder)
    with pytest.raises(IndexNotFound):
        search(SearchRequest(repository_id="unknown", query="retry backoff", mode="semantic"), embedder)


def test_index_reloads_from_disk_and_reuses_embeddings(indexed):
    run, embedder = indexed
    summary, index = run()
    registry._items.clear()
    reloaded = registry.get(summary.id)
    assert reloaded is not index and [u.unit_id for u in reloaded.units] == [u.unit_id for u in index.units]
    reloaded.ensure_embeddings(embedder)
    assert reloaded.embeddings.shape == index.embeddings.shape


def test_python_units_still_retrievable(indexed, tmp_path):
    repo = tmp_path / "py"
    repo.mkdir()
    (repo / "tax.py").write_text('def vat(amount):\n    """Add value added tax to an amount."""\n    return amount * 1.2\n', encoding="utf-8")
    run, embedder = indexed
    summary, _ = run(repo)
    top = search(SearchRequest(repository_id=summary.id, query="value added tax amount", mode="semantic", top_k=1), embedder).results[0]
    assert top.language == "Python" and top.name == "vat" and (top.line_start, top.line_end) == (1, 3)


def test_retrieval_units_keep_file_units_only_without_finer_units():
    from app.models.schemas import CodeUnit
    mk = lambda t, path, name: CodeUnit(unit_id=name, repository_id="r", commit_sha="c", language="JavaScript", unit_type=t, name=name,
                                        qualified_name=name, file_path=path, line_start=1, line_end=1, source="x")
    units = [mk("file", "a.js", "a.js"), mk("function", "a.js", "f"), mk("file", "b.js", "b.js")]
    assert [u.unit_id for u in retrieval_units(units)] == ["f", "b.js"]
