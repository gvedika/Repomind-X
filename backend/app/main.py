from __future__ import annotations
import logging
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from app.models.schemas import IngestRequest, QueryRequest, QueryResponse, RepositorySummary, SearchRequest, SearchResponse, SourceStatus
from app.retrieval.service import IndexNotFound, registry, search as retrieval_search
from app.retrieval.source import verify_source
from app.services.ingestion import ingest
from app.services.orchestrator import answer
from app.services.store import store
from contextlib import asynccontextmanager
from app.services.graph_backend import get_production_backend
from app.services.vector import ChromaVectorStore
from app.core.config import settings
from app.security.prompt_guard import detect_repository_instruction

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
@asynccontextmanager
async def lifespan(_app):
    store.restore()
    yield

app=FastAPI(title="RepoMind-X API",version="0.2.0",description="Retrieval-first code intelligence: ranked, source-verified code units for natural-language questions",lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173","http://127.0.0.1:5173","http://localhost:4173","http://127.0.0.1:4173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


def state_or_404(repository_id: str):
    state = store.get(repository_id)
    if not state: raise HTTPException(404, "Repository is not indexed. Ingest it first.")
    return state


@app.get("/health")
def health() -> dict: return {"status":"ok","repositories":len(store.all())}

@app.get("/health/dependencies")
def dependency_health() -> dict:
    checks={}
    try:
        backend=get_production_backend(); checks["neo4j"]=backend.health(); backend.close()
    except Exception as exc: checks["neo4j"]=False; checks["neo4j_error"]=str(exc)
    try:
        if not settings.chroma_host: raise RuntimeError("CHROMA_HOST not configured")
        client=ChromaVectorStore("healthcheck").client
        client.heartbeat()
        checks["chromadb"]=True
    except Exception as exc: checks["chromadb"]=False; checks["chromadb_error"]=str(exc)
    checks["status"]="ok" if checks.get("neo4j") and checks.get("chromadb") else "degraded"
    return checks


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/api/repositories/ingest", response_model=RepositorySummary, status_code=201)
def ingest_repository(request: IngestRequest) -> RepositorySummary:
    try: return ingest(request)
    except Exception as exc:
        logging.exception("Ingestion failed")
        raise HTTPException(422, f"Ingestion failed: {exc}") from exc


@app.get("/api/repositories", response_model=list[RepositorySummary])
def list_repositories() -> list[RepositorySummary]: return store.all()


@app.get("/api/repositories/{repository_id}", response_model=RepositorySummary)
def get_repository(repository_id: str) -> RepositorySummary: return state_or_404(repository_id).summary


@app.get("/api/repositories/{repository_id}/graph")
def get_graph(repository_id: str, limit: int = Query(250, ge=1, le=1000)) -> dict: return state_or_404(repository_id).graph.export(limit)


@app.get("/api/repositories/{repository_id}/impact")
def impact(repository_id: str, symbol: str = Query(min_length=1)) -> dict:
    state = state_or_404(repository_id); nodes = state.graph.impact(symbol)
    return {"symbol": symbol, "affected": [node.model_dump() for node in nodes], "confidence": min(0.95, 0.4 + len(nodes) * 0.05)}


@app.get("/api/repositories/{repository_id}/findings")
def findings(repository_id: str) -> list[dict]: return [f.model_dump() for f in state_or_404(repository_id).findings]


@app.post("/api/search", response_model=SearchResponse)
def search_code(request: SearchRequest) -> SearchResponse:
    """Primary Theme 1 operation: ranked code units with exact repository-relative paths and one-based line spans."""
    try: return retrieval_search(request)
    except IndexNotFound as exc: raise HTTPException(404, str(exc)) from exc
    except ValueError as exc: raise HTTPException(400, str(exc)) from exc


@app.get("/api/repositories/{repository_id}/units/{unit_id}")
def unit_source(repository_id: str, unit_id: str, commit_sha: str | None = None) -> dict:
    """Full verified source of one indexed unit (bounded), for opening a result in the UI."""
    try: index = registry.get(repository_id, commit_sha)
    except IndexNotFound as exc: raise HTTPException(404, str(exc)) from exc
    unit = index.by_id.get(unit_id) or next((u for u in index.all_units if u.unit_id == unit_id), None)
    if unit is None: raise HTTPException(404, "Unknown unit id for this repository and commit.")
    check = verify_source(index.root, unit, index.repository_id, index.commit_sha, max_lines=400, max_chars=40000)
    if check.status in {SourceStatus.INVALID, SourceStatus.MISSING}: raise HTTPException(410, "; ".join(check.warnings))
    return {"unit": unit.model_dump(exclude={"source"}), "source": check.excerpt, "source_status": check.status,
            "excerpt_line_end": check.excerpt_line_end, "truncated": check.truncated, "warnings": check.warnings,
            "callers": [e.as_dict({u.unit_id: u for u in index.all_units}) for e in index.graph.callers(unit.unit_id)][:20],
            "callees": [e.as_dict({u.unit_id: u for u in index.all_units}) for e in index.graph.callees(unit.unit_id)][:20],
            "unresolved_calls": index.graph.unresolved.get(unit.unit_id, [])[:20]}


@app.post("/api/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    if detect_repository_instruction(request.question):
        raise HTTPException(400, "Potential prompt-injection instruction detected; repository analysis treats repository content as untrusted data.")
    return answer(state_or_404(request.repository_id), request.question)


@app.post("/api/repositories/{repository_id}/memory")
def remember(repository_id: str, note: str = Query(min_length=3)) -> dict:
    state_or_404(repository_id).memories.append(note)
    return {"stored": True, "memory_count": len(state_or_404(repository_id).memories)}
