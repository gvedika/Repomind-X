"""Custom repository benchmark (distinct from the official CoIR/MTEB screening run in coir_apps.py).

Every system ranks the same canonical code-unit type for the same queries, so metrics are directly comparable.
Results are produced only by executing the retrieval service; nothing is estimated."""
from __future__ import annotations
import json
from pathlib import Path
from app.evaluation.retrieval_eval import evaluate
from app.models.schemas import RetrievalMode

SYSTEMS = {"semantic": RetrievalMode.SEMANTIC, "lexical": RetrievalMode.LEXICAL, "hybrid": RetrievalMode.HYBRID,
           "hybrid_rerank": RetrievalMode.HYBRID_RERANK, "adaptive": RetrievalMode.ADAPTIVE}


def run_all(repository_id: str, dataset_path: Path, systems: list[str] | None = None) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    modes = [SYSTEMS[name] for name in (systems or list(SYSTEMS))]
    return evaluate(repository_id, dataset, modes)
