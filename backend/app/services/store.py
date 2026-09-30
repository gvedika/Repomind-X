from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
from app.core.config import settings
from app.models.schemas import Finding,RepositorySummary
from app.services.graph import KnowledgeGraph
from app.services.graph_backend import InMemoryGraphBackend, get_production_backend
from app.services.git_history import GitEvolution
from app.services.vector import ChromaVectorStore


@dataclass
class RepositoryState:
    summary:RepositorySummary
    graph:KnowledgeGraph
    vectors:ChromaVectorStore|None
    git:GitEvolution
    findings:list[Finding]
    memories:list[str]=field(default_factory=list)
    root:Path|None=None


class RepositoryStore:
    """States keyed by (repository_id, commit_sha); lookups without a commit return the most recently indexed one."""
    def __init__(self): self._items={}
    def add(self,state): self._items[(state.summary.id,state.summary.commit_sha)]=state
    def get(self,repository_id,commit_sha=None):
        matches=[v for (rid,sha),v in self._items.items() if rid==repository_id and (commit_sha is None or sha==commit_sha)]
        return max(matches,key=lambda s:s.summary.indexed_at) if matches else None
    def remove(self,repository_id,commit_sha): return self._items.pop((repository_id,commit_sha),None)
    def all(self): return sorted((item.summary for item in self._items.values()),key=lambda s:s.indexed_at)

    def restore(self):
        root=Path(settings.repository_root)
        if not root.exists(): return
        backend=None
        if settings.graph_backend=="neo4j":
            try: backend=get_production_backend()
            except Exception: backend=None
        if backend is None: backend=InMemoryGraphBackend()
        for summary_path in root.glob("*/.repomind/summary.json"):
            try:
                summary=RepositorySummary.model_validate(json.loads(summary_path.read_text(encoding="utf-8")))
                repo_root=summary_path.parent.parent
                graph=KnowledgeGraph(summary.id,backend)
                vectors=ChromaVectorStore(summary.id) if settings.chroma_host else None
                findings=[]
                findings_path=summary_path.parent/"findings.json"
                if findings_path.exists():
                    findings=[Finding.model_validate(x) for x in json.loads(findings_path.read_text(encoding="utf-8"))]
                self.add(RepositoryState(summary,graph,vectors,GitEvolution.mine(repo_root),findings,root=repo_root))
            except Exception:
                continue


store=RepositoryStore()
