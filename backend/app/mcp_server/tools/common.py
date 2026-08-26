from app.services.graph_backend import get_production_backend
from app.models.schemas import NodeKind
from app.services.vector import ChromaVectorStore
from app.services.security import scan_python
from app.core.config import settings
from pathlib import Path


def graph(repository_id):
    return get_production_backend()


def repository_root(repository_id):
    backend=graph(repository_id)
    nodes=backend.search(repository_id,repository_id,{NodeKind.REPOSITORY})
    if not nodes: raise ValueError("Repository is not indexed in Neo4j.")
    root=nodes[0].metadata.get("root")
    if not root: raise ValueError("Repository root metadata is missing.")
    path=Path(root).resolve()
    allowed=Path(settings.repository_root).resolve()
    try:
        path.relative_to(allowed)
    except ValueError as exc:
        raise ValueError("Repository root is outside the configured repository sandbox.") from exc
    if not path.is_dir():
        raise ValueError("Indexed repository root does not exist.")
    return path


def vector(repository_id):
    return ChromaVectorStore(repository_id)
