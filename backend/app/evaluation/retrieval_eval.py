"""Custom retrieval benchmark: every mode ranks the same canonical code units for the same queries.

This is separate from the official CoIR Apps Retrieval/MTEB evaluation (app/evaluation/coir_apps.py).
Relevance labels are symbol qualified names (optionally file-qualified as "path::qualified_name")."""
from __future__ import annotations
import argparse
import json
import statistics
from pathlib import Path
from time import perf_counter
from app.evaluation.metrics import ndcg_at_k, reciprocal_rank, recall_at_k
from app.models.schemas import IngestRequest, RetrievalMode, SearchRequest
from app.retrieval.service import search

MODES = [RetrievalMode.SEMANTIC, RetrievalMode.LEXICAL, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK]


def _relevant_ids(index, labels: list[str]) -> set[str]:
    ids = set()
    for label in labels:
        path, _, name = label.rpartition("::")
        matches = {u.unit_id for u in index.units if u.qualified_name == name and (not path or u.file_path == path)}
        if not matches: raise ValueError(f"label {label!r} does not match any indexed unit")
        ids |= matches
    return ids


def evaluate(repository_id: str, dataset: dict, modes=MODES, k: int = 10, embedder=None, reranker=None) -> dict:
    from app.retrieval.service import registry
    index = registry.get(repository_id)
    rows = [(q, _relevant_ids(index, q["relevant"])) for q in dataset["queries"]]
    report = {"split": dataset.get("split"), "queries": len(rows), "units": len(index.units), "k": k, "modes": {}}
    for mode in modes:
        per_query, latencies = [], []
        for query, relevant in rows:
            started = perf_counter()
            response = search(SearchRequest(repository_id=repository_id, query=query["query"], mode=mode, top_k=k), embedder, reranker)
            latencies.append((perf_counter() - started) * 1000)
            ids = [r.unit_id for r in response.results]
            per_query.append({"id": query["id"], "rr": reciprocal_rank(ids, relevant), "r1": recall_at_k(ids, relevant, 1),
                              "r5": recall_at_k(ids, relevant, 5), "r10": recall_at_k(ids, relevant, k), "ndcg": ndcg_at_k(ids, relevant, k),
                              "top": response.results[0].qualified_name if response.results else None})
        mean = lambda key: round(statistics.fmean(r[key] for r in per_query), 4)
        report["modes"][mode.value] = {"mrr@10": mean("rr"), "recall@1": mean("r1"), "recall@5": mean("r5"), f"recall@{k}": mean("r10"),
                                       f"ndcg@{k}": mean("ndcg"), "latency_ms_p50": round(statistics.median(latencies), 2),
                                       "misses_at_1": [r["id"] for r in per_query if r["r1"] == 0]}
    return report


def main():
    parser = argparse.ArgumentParser(description="Compare RepoMind-X retrieval modes on a labelled query set.")
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source", help="repository to ingest before evaluating (defaults to the dataset's repository)")
    parser.add_argument("--repository-id")
    parser.add_argument("--modes", nargs="*", default=[m.value for m in MODES])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    repository_id = args.repository_id
    if not repository_id:
        from app.services.ingestion import ingest
        source = args.source or str((Path(__file__).resolve().parents[3] / dataset["repository"]))
        repository_id = ingest(IngestRequest(source=source)).id
    report = evaluate(repository_id, dataset, [RetrievalMode(m) for m in args.modes])
    text = json.dumps(report, indent=2)
    if args.output: args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
