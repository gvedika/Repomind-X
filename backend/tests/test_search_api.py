from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.core.config import settings
from app.retrieval import embedding
from app.retrieval.embedding import HashingEmbedder
from app.retrieval.service import registry

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_js_repo"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.main import app
    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", None)
    monkeypatch.setattr(embedding, "_default", HashingEmbedder())   # no model download in tests
    with TestClient(app) as test_client:
        yield test_client
    registry._items.clear()


def _ingest(client):
    response = client.post("/api/repositories/ingest", json={"source": str(SAMPLE)})
    assert response.status_code == 201, response.text
    return response.json()


def test_ingest_reports_language_coverage_and_commit(client):
    repo = _ingest(client)
    assert repo["languages"] == {"JavaScript": 7} and repo["parse_coverage"]["ratio"] == 1.0 and repo["commit_sha"]


def test_search_returns_ranked_units_with_exact_locations(client):
    repo = _ingest(client)
    body = {"repository_id": repo["id"], "query": "retry an operation with exponential backoff", "top_k": 3, "commit_sha": repo["commit_sha"]}
    data = client.post("/api/search", json=body).json()
    assert data["mode"] == "hybrid" and data["repository_id"] == repo["id"] and data["commit_sha"] == repo["commit_sha"]
    top = data["results"][0]
    assert top["qualified_name"] == "withRetry" and top["file_path"] == "src/utils/retry.cjs"
    assert (top["line_start"], top["line_end"]) == (6, 17) and top["excerpt"].startswith("async function withRetry(")
    assert {"lexical", "semantic", "rrf"} <= set(top["score_components"]) and top["source_status"] == "verified"
    assert data["trace"] and data["latency_ms"] >= 0 and data["tool_calls"] == 3


def test_baseline_and_adaptive_are_comparable(client):
    repo = _ingest(client)
    base = {"repository_id": repo["id"], "query": "which handlers call withRetry before chargeCard", "top_k": 5}
    hybrid = client.post("/api/search", json={**base, "mode": "hybrid"}).json()
    adaptive = client.post("/api/search", json={**base, "mode": "adaptive"}).json()
    assert hybrid["stop_reason"] == "single_pass" and adaptive["stop_reason"] == "structural_answer"
    assert adaptive["results"][0]["qualified_name"] == "router.post('/orders')"
    assert set(hybrid["results"][0]) == set(adaptive["results"][0])      # same result contract


def test_unit_source_endpoint(client):
    repo = _ingest(client)
    top = client.post("/api/search", json={"repository_id": repo["id"], "query": "authenticate user and issue token"}).json()["results"]
    login = next(r for r in top if r["qualified_name"] == "login")
    data = client.get(f"/api/repositories/{repo['id']}/units/{login['unit_id']}").json()
    assert data["source_status"] == "verified" and data["source"].startswith("export async function login")
    assert any(c["to_name"].endswith("::findUserByEmail") for c in data["callees"])
    assert client.get(f"/api/repositories/{repo['id']}/units/cu_nope").status_code == 404


def test_error_states(client):
    repo = _ingest(client)
    assert client.post("/api/search", json={"repository_id": "missing", "query": "anything"}).status_code == 404
    assert client.post("/api/search", json={"repository_id": repo["id"], "query": "x"}).status_code == 422
    assert client.post("/api/search", json={"repository_id": repo["id"], "query": "abc", "mode": "magic"}).status_code == 422
    assert client.post("/api/search", json={"repository_id": repo["id"], "query": "abc", "commit_sha": "deadbeef"}).status_code == 404
    empty = client.post("/api/search", json={"repository_id": repo["id"], "query": "zzqqxx", "mode": "lexical"}).json()
    assert empty["results"] == [] and "no matching code units" in empty["warnings"]


def test_partial_parse_warning_is_surfaced(client, tmp_path):
    repo_dir = tmp_path / "broken"
    repo_dir.mkdir()
    (repo_dir / "ok.js").write_text("export function parseInvoice(text) { return text.split(','); }\n", encoding="utf-8")
    (repo_dir / "bad.js").write_text("function oops( {\n", encoding="utf-8")
    repo = client.post("/api/repositories/ingest", json={"source": str(repo_dir)}).json()
    assert repo["parse_coverage"]["files_partial"] == 1
    data = client.post("/api/search", json={"repository_id": repo["id"], "query": "parse invoice text"}).json()
    assert any("partial parse coverage" in w for w in data["warnings"])
