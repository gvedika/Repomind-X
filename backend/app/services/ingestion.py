from __future__ import annotations
import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from git import Repo
from app.core.config import settings
from app.models.schemas import IngestRequest, RepositorySummary, GraphNode, NodeKind, UnitType
from app.retrieval.documents import document_text, retrieval_units
from app.retrieval.embedding import Embedder, default_embedder
from app.retrieval.index import CodeIndex
from app.retrieval.service import registry
from app.services.analyzer import PythonAnalyzer
from app.services.code_units import AnalysisContext, analyze_repository
from app.services.js_analyzer import JavaScriptAnalyzer
from app.services.git_history import GitEvolution
from app.services.graph import build_graph
from app.services.graph_backend import InMemoryGraphBackend
from app.services.risk import repository_risk
from app.services.security import scan_python
from app.services.store import RepositoryState, store
from app.services.vector import ChromaVectorStore, VectorDocument
from app.security.input_validation import validate_repository_source


logger = logging.getLogger(__name__)
ANALYZERS = (JavaScriptAnalyzer(), PythonAnalyzer())


def _commit_sha(path: Path) -> str:
    """HEAD of the source checkout; 'worktree' when the source is not a Git repository."""
    try: return Repo(path, search_parent_directories=True).head.commit.hexsha
    except Exception: return "worktree"


def _materialize(request: IngestRequest) -> tuple[Path, str]:
    source = validate_repository_source(request.source)
    local=Path(source).expanduser()
    if local.exists() and local.is_dir():
        settings.repository_root.mkdir(parents=True,exist_ok=True)
        target=settings.repository_root/f"local-{hashlib.sha1(str(local.resolve()).encode()).hexdigest()[:12]}"
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(local,target,ignore=shutil.ignore_patterns(".git","__pycache__","node_modules","dist","build",".venv","venv"))
        return target.resolve(), _commit_sha(local)
    if not source.startswith(("https://", "git@")):
        raise ValueError("source must be a local directory or a public Git URL")
    settings.repository_root.mkdir(parents=True, exist_ok=True)
    target = settings.repository_root / f"clone-{uuid4().hex[:10]}"
    Repo.clone_from(source, target, branch=request.branch, depth=300)
    return target, _commit_sha(target)


def _architecture(analyses) -> str:
    imports = {imp.split(".")[0] for a in analyses for imp in a.imports}
    js_imports = {imp.removeprefix("node:").split("/")[0] for a in analyses if a.language == "JavaScript" for imp in a.imports}
    if {"express", "koa", "fastify", "@nestjs", "hapi"} & js_imports: return "JavaScript web service / API"
    if {"react", "vue", "svelte", "@angular", "next"} & js_imports: return "JavaScript front-end application"
    if any(a.language == "JavaScript" for a in analyses) and not any(a.language == "Python" for a in analyses): return "modular JavaScript application"
    if {"fastapi", "flask", "django"} & imports: return "web service / API"
    if {"sqlalchemy", "django"} & imports: return "data-backed application"
    if any("cli" in a.path.lower() for a in analyses): return "command-line application"
    return "modular Python application"


def _graph(repository_id, analyses):
    """Neo4j when configured and reachable; otherwise an in-process graph so retrieval still works on a CPU laptop."""
    try: return build_graph(repository_id, analyses)
    except Exception as exc:
        if settings.graph_backend != "neo4j" or not settings.allow_graph_fallback: raise
        logger.warning("Neo4j unavailable (%s); using in-memory graph for %s", exc, repository_id)
        return build_graph(repository_id, analyses, backend=InMemoryGraphBackend())


def _vector_documents(repository_id, commit_sha, root, analyses):
    documents: list[VectorDocument] = []
    for analysis in analyses:
        content = " ".join([analysis.path, *analysis.imports])
        documents.append(VectorDocument(f"file:{analysis.path}", content, {"repository_id": repository_id, "file_path": analysis.path, "entity_type": "file", "language": analysis.language, "commit_sha": commit_sha}))
        for unit in retrieval_units(analysis.units):
            if unit.unit_type == UnitType.FILE: continue
            entity = "class" if unit.unit_type == UnitType.CLASS else "function"
            documents.append(VectorDocument(unit.unit_id, document_text(unit), {"repository_id": repository_id, "file_path": unit.file_path, entity: unit.qualified_name,
                "entity_type": entity, "language": unit.language, "commit_sha": commit_sha, "unit_id": unit.unit_id, "line_start": unit.line_start, "line_end": unit.line_end}))
    for documentation in (root / "README.md", root / "README.rst"):
        if documentation.exists():
            documents.append(VectorDocument(f"doc:{documentation.name}", documentation.read_text(encoding="utf-8", errors="ignore"), {"repository_id": repository_id, "file_path": documentation.name, "entity_type": "documentation"}))
    return documents


def ingest(request: IngestRequest, embedder: Embedder | None = None, build_embeddings: bool = True) -> RepositorySummary:
    root, commit_sha = _materialize(request)
    repository_id = hashlib.sha1(str(root).encode()).hexdigest()[:12]
    analyses, coverage = analyze_repository(root, ANALYZERS, AnalysisContext(repository_id, commit_sha))
    graph = _graph(repository_id, analyses)
    # Persist repository root/source metadata in the graph so the MCP server can resolve state across processes.
    graph.backend.add_node(GraphNode(id=f"repo:{repository_id}", kind=NodeKind.REPOSITORY, name=root.name, metadata={"source": request.source, "root": str(root), "commit_sha": commit_sha}), repository_id)
    vectors = None
    if settings.chroma_host:
        vectors = ChromaVectorStore(repository_id)
        vectors.upsert(_vector_documents(repository_id, commit_sha, root, analyses))
    all_functions = [fun for analysis in analyses for fun in analysis.functions]
    history, findings = GitEvolution.mine(root), scan_python(root)
    languages = dict(coverage.by_language)
    dependencies = sorted({imp.split(".")[0] for analysis in analyses for imp in analysis.imports})
    summary = RepositorySummary(id=repository_id, name=root.name, source=request.source, languages=languages, files=len(analyses), functions=len(all_functions), classes=sum(len(a.classes) for a in analyses), dependencies=dependencies[:100], architecture=_architecture(analyses), risk_score=repository_risk(all_functions, history, findings), indexed_at=datetime.now(timezone.utc), commit_sha=commit_sha, units=coverage.units, parse_coverage=coverage)
    metadata_dir=root/".repomind"; metadata_dir.mkdir(parents=True,exist_ok=True)
    (metadata_dir/"summary.json").write_text(summary.model_dump_json(indent=2),encoding="utf-8")
    with (metadata_dir/"units.jsonl").open("w",encoding="utf-8") as handle:
        for analysis in analyses:
            for unit in analysis.units: handle.write(unit.model_dump_json()+"\n")
    (metadata_dir/"findings.json").write_text(json.dumps([f.model_dump() for f in findings],indent=2),encoding="utf-8")
    (metadata_dir/"embeddings.npz").unlink(missing_ok=True)
    index = CodeIndex(repository_id, commit_sha, root, [u for a in analyses for u in a.units], coverage)
    if build_embeddings: index.ensure_embeddings(embedder or default_embedder())
    registry.forget(repository_id); registry.register(index)
    state=RepositoryState(summary=summary,graph=graph,vectors=vectors,git=history,findings=findings,root=root)
    store.add(state)
    return summary
