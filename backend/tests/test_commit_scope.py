from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from git import Actor, Repo
from app.core.config import settings
from app.models.schemas import IngestRequest, SearchRequest, SourceStatus
from app.retrieval import embedding
from app.retrieval.embedding import HashingEmbedder
from app.retrieval.service import IndexNotFound, registry, search
from app.services.code_units import split_lines

AUTHOR = Actor("fixture", "fixture@example.invalid")


def _commit(repo: Repo, files: dict[str, str | None], message: str) -> str:
    root = Path(repo.working_tree_dir)
    for rel, text in files.items():
        path = root / rel
        if text is None:
            repo.index.remove([rel], working_tree=True)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        repo.index.add([rel])
    return repo.index.commit(message, author=AUTHOR, committer=AUTHOR).hexsha


@pytest.fixture
def two_commits(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", None)
    monkeypatch.setattr(embedding, "_default", HashingEmbedder())
    source = tmp_path / "shop"
    repo = Repo.init(source)
    first = _commit(repo, {"src/cart.js": "export function applyDiscount(price, pct) {\n  return price - price * pct;\n}\n",
                           "src/tax.js": "export function addTax(amount) {\n  return amount * 1.2;\n}\n"}, "v1")
    second = _commit(repo, {"src/cart.js": None,
                            "src/pricing/discount.js": "// moved and extended\n\nexport function applyDiscount(price, pct, cap = 50) {\n  const off = Math.min(price * pct, cap);\n  return price - off;\n}\n",
                            "src/tax.js": "export function addTax(amount, rate = 0.2) {\n  return amount * (1 + rate);\n}\n\nexport function removeTax(amount, rate = 0.2) {\n  return amount / (1 + rate);\n}\n"}, "v2")
    yield source, repo, first, second
    registry._items.clear()
    repo.close()


def _ingest(source, commit=None):
    from app.services.ingestion import ingest
    return ingest(IngestRequest(source=str(source), commit=commit), embedder=HashingEmbedder())


def test_two_commits_index_and_query_independently(two_commits):
    source, repo, first, second = two_commits
    v1, v2 = _ingest(source, first), _ingest(source, second)
    assert v1.id == v2.id and (v1.commit_sha, v2.commit_sha) == (first, second)
    embedder = HashingEmbedder()
    r1 = search(SearchRequest(repository_id=v1.id, query="apply discount to price", commit_sha=first, top_k=5), embedder)
    r2 = search(SearchRequest(repository_id=v1.id, query="apply discount to price", commit_sha=second, top_k=5), embedder)
    assert r1.commit_sha == first and r2.commit_sha == second
    top1, top2 = r1.results[0], r2.results[0]
    assert (top1.file_path, top1.line_start, top1.line_end) == ("src/cart.js", 1, 3)
    assert (top2.file_path, top2.line_start, top2.line_end) == ("src/pricing/discount.js", 3, 6)
    assert top1.unit_id != top2.unit_id
    # No leakage: v1 never returns v2-only files/symbols and vice versa.
    assert all(r.file_path != "src/pricing/discount.js" for r in r1.results)
    assert all(r.file_path != "src/cart.js" for r in r2.results)
    v1_names = {r.qualified_name for r in search(SearchRequest(repository_id=v1.id, query="remove tax from amount", commit_sha=first, top_k=10), embedder).results}
    assert "removeTax" not in v1_names


def test_spans_validate_against_each_commit_tree(two_commits):
    source, repo, first, second = two_commits
    repository_id = _ingest(source, first).id
    _ingest(source, second)
    for sha in (first, second):
        index = registry.get(repository_id, sha)
        for unit in index.units:
            blob = repo.commit(sha).tree / unit.file_path
            lines = split_lines(blob.data_stream.read().decode("utf-8"))
            assert unit.source == "\n".join(lines[unit.line_start - 1:unit.line_end]), (sha, unit.qualified_name)
            assert unit.commit_sha == sha


def test_default_ingest_uses_head_and_marks_dirty_worktree(two_commits):
    source, repo, first, second = two_commits
    assert _ingest(source).commit_sha == second
    (source / "src/tax.js").write_text("export function addTax(amount) { return amount; }\n", encoding="utf-8")
    dirty = _ingest(source)
    assert dirty.commit_sha == f"{second}-dirty"
    top = search(SearchRequest(repository_id=dirty.id, query="add tax", commit_sha=dirty.commit_sha, top_k=1), HashingEmbedder()).results[0]
    assert top.line_end == 1 and top.source_status == SourceStatus.VERIFIED


def test_reindex_and_delete_one_version_keeps_the_other(two_commits):
    from app.services.ingestion import delete_version
    source, repo, first, second = two_commits
    v1 = _ingest(source, first); _ingest(source, second)
    _ingest(source, first)                         # re-index v1 in place
    assert sorted(registry.commits(v1.id)) == sorted([first, second])
    assert delete_version(v1.id, first)
    with pytest.raises(IndexNotFound): registry.get(v1.id, first)
    registry._items.clear()                        # v2 must still load from disk
    assert registry.get(v1.id, second).commit_sha == second
    assert not delete_version(v1.id, first)


def test_commit_scoped_api(two_commits):
    from app.main import app
    source, repo, first, second = two_commits
    with TestClient(app) as client:
        v1 = client.post("/api/repositories/ingest", json={"source": str(source), "commit": first}).json()
        client.post("/api/repositories/ingest", json={"source": str(source), "commit": second})
        commits = {c["commit_sha"] for c in client.get(f"/api/repositories/{v1['id']}/commits").json()}
        assert commits == {first, second}
        data = client.post("/api/search", json={"repository_id": v1["id"], "query": "apply discount", "commit_sha": first}).json()
        assert data["commit_sha"] == first and data["results"][0]["file_path"] == "src/cart.js"
        assert client.post("/api/repositories/ingest", json={"source": str(source), "commit": "--upload-pack=x"}).status_code == 422
        assert client.delete(f"/api/repositories/{v1['id']}/commits/{first}").json()["deleted"]
        assert client.post("/api/search", json={"repository_id": v1["id"], "query": "apply discount", "commit_sha": first}).status_code == 404
