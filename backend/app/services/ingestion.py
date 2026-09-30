from __future__ import annotations
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from git import Repo
from app.core.config import settings
from app.models.schemas import IngestRequest, RepositorySummary, GraphNode, NodeKind
from app.services.analyzer import PythonAnalyzer
from app.services.code_units import AnalysisContext, analyze_repository
from app.services.js_analyzer import JavaScriptAnalyzer
from app.services.git_history import GitEvolution
from app.services.graph import build_graph
from app.services.risk import repository_risk
from app.services.security import scan_python
from app.services.store import RepositoryState, store
from app.services.vector import ChromaVectorStore, VectorDocument
from app.security.input_validation import validate_repository_source


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


def ingest(request: IngestRequest) -> RepositorySummary:
    root, commit_sha = _materialize(request)
    repository_id = hashlib.sha1(str(root).encode()).hexdigest()[:12]
    analyses, coverage = analyze_repository(root, ANALYZERS, AnalysisContext(repository_id, commit_sha))
    graph = build_graph(repository_id, analyses)
    # Persist repository root/source metadata in Neo4j so the MCP server can resolve state across processes.
    graph.backend.add_node(GraphNode(id=f"repo:{repository_id}", kind=NodeKind.REPOSITORY, name=root.name, metadata={"source": request.source, "root": str(root)}), repository_id)
    vectors = ChromaVectorStore(repository_id); documents: list[VectorDocument] = []; all_functions = []
    for analysis in analyses:
        content = " ".join([analysis.path, *analysis.imports])
        documents.append(VectorDocument(f"file:{analysis.path}", content, {"repository_id": repository_id, "file_path": analysis.path, "entity_type": "file"}))
        def unit_id_for(fun):
            return next((u.unit_id for u in analysis.units if u.qualified_name == fun.qualified_name and u.line_start <= fun.line_start <= u.line_end), "")
        for fun in analysis.functions:
            all_functions.append(fun)
            text = " ".join(filter(None, [fun.qualified_name, fun.docstring, " ".join(fun.calls), " ".join(fun.parameters)]))
            documents.append(VectorDocument(f"function:{analysis.path}:{fun.qualified_name}", text, {"repository_id": repository_id, "file_path": analysis.path, "function": fun.qualified_name, "entity_type": "function", "language": analysis.language, "commit_sha": commit_sha, "unit_id": unit_id_for(fun)}))
        for cls in analysis.classes:
            documents.append(VectorDocument(f"class:{analysis.path}:{cls['name']}", f"{cls['name']} {' '.join(cls['bases'])} {' '.join(cls['methods'])}", {"repository_id": repository_id, "file_path": analysis.path, "class": cls["name"], "entity_type": "class"}))
    for documentation in (root / "README.md", root / "README.rst"):
        if documentation.exists():
            documents.append(VectorDocument(f"doc:{documentation.name}", documentation.read_text(encoding="utf-8", errors="ignore"), {"repository_id": repository_id, "file_path": documentation.name, "entity_type": "documentation"}))
    vectors.upsert(documents)
    history, findings = GitEvolution.mine(root), scan_python(root)
    languages = dict(coverage.by_language)
    dependencies = sorted({imp.split(".")[0] for analysis in analyses for imp in analysis.imports})
    summary = RepositorySummary(id=repository_id, name=root.name, source=request.source, languages=languages, files=len(analyses), functions=len(all_functions), classes=sum(len(a.classes) for a in analyses), dependencies=dependencies[:100], architecture=_architecture(analyses), risk_score=repository_risk(all_functions, history, findings), indexed_at=datetime.now(timezone.utc), commit_sha=commit_sha, units=coverage.units, parse_coverage=coverage)
    state=RepositoryState(summary=summary,graph=graph,vectors=vectors,git=history,findings=findings)
    store.add(state)
    metadata_dir=root/".repomind"; metadata_dir.mkdir(parents=True,exist_ok=True)
    (metadata_dir/"summary.json").write_text(summary.model_dump_json(indent=2),encoding="utf-8")
    with (metadata_dir/"units.jsonl").open("w",encoding="utf-8") as handle:
        for analysis in analyses:
            for unit in analysis.units: handle.write(unit.model_dump_json()+"\n")
    (metadata_dir/"findings.json").write_text(__import__("json").dumps([f.model_dump() for f in findings],indent=2),encoding="utf-8")
    return summary
