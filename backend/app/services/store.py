from __future__ import annotations
import json
from dataclasses import dataclass,field
from pathlib import Path
from app.core.config import settings
from app.models.schemas import Finding,RepositorySummary
from app.services.graph import KnowledgeGraph
from app.services.graph_backend import get_production_backend
from app.services.git_history import GitEvolution
from app.services.vector import ChromaVectorStore


@dataclass
class RepositoryState:
    summary:RepositorySummary
    graph:KnowledgeGraph
    vectors:ChromaVectorStore
    git:GitEvolution
    findings:list[Finding]
    memories:list[str]=field(default_factory=list)


class RepositoryStore:
    def __init__(self): self._items={}
    def add(self,state): self._items[state.summary.id]=state
    def get(self,repository_id): return self._items.get(repository_id)
    def all(self): return [item.summary for item in self._items.values()]

    def restore(self):
        root=Path(settings.repository_root)
        if not root.exists(): return
        try: backend=get_production_backend()
        except Exception: return
        for summary_path in root.glob("*/.repomind/summary.json"):
            try:
                summary=RepositorySummary.model_validate(json.loads(summary_path.read_text(encoding="utf-8")))
                repo_root=summary_path.parent.parent
                graph=KnowledgeGraph(summary.id,backend)
                vectors=ChromaVectorStore(summary.id)
                findings=[]
                findings_path=summary_path.parent/"findings.json"
                if findings_path.exists():
                    findings=[Finding.model_validate(x) for x in json.loads(findings_path.read_text(encoding="utf-8"))]
                self.add(RepositoryState(summary,graph,vectors,GitEvolution.mine(repo_root),findings))
            except Exception:
                continue


store=RepositoryStore()
