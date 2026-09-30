"""Custom retrieval benchmark: every mode ranks the same canonical code units for the same queries.

This is separate from the official CoIR Apps Retrieval/MTEB evaluation (app/evaluation/coir_apps.py).
Relevance labels are symbol qualified names (optionally file-qualified as "path::qualified_name")."""
from __future__ import annotations
import argparse
import json
import math
import statistics
from pathlib import Path
from time import perf_counter
from app.evaluation.metrics import ndcg_at_k, precision_at_k, reciprocal_rank, recall_at_k
from app.models.schemas import IngestRequest, RetrievalMode, SearchRequest
from app.retrieval.service import search

MODES = [RetrievalMode.SEMANTIC, RetrievalMode.LEXICAL, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK, RetrievalMode.ADAPTIVE]


def _relevant_ids(index, labels: list[str]) -> set[str]:
    ids = set()
    for label in labels:
        path, _, name = label.rpartition("::")
        matches = {u.unit_id for u in index.units if u.qualified_name == name and (not path or u.file_path == path)}
        if not matches: raise ValueError(f"label {label!r} does not match any indexed unit")
        ids |= matches
    return ids


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    if not ordered: return 0.0
    rank = max(0, min(len(ordered) - 1, math.ceil(pct / 100 * len(ordered)) - 1))   # nearest-rank method
    return ordered[rank]


def index_stats(index) -> dict:
    meta = index.root / ".repomind"
    size = sum(f.stat().st_size for f in meta.glob("*") if f.is_file()) if meta.exists() else 0
    return {"retrievable_units": len(index.units), "all_units": len(index.all_units), "index_bytes": size,
            "embedding_model": index.embedder_name}


def evaluate(repository_id: str, dataset: dict, modes=MODES, k: int = 10, embedder=None, reranker=None) -> dict:
    from app.retrieval.service import registry
    index = registry.get(repository_id)
    rows = [(q, _relevant_ids(index, q["relevant"])) for q in dataset["queries"]]
    report = {"split": dataset.get("split"), "queries": len(rows), "units": len(index.units), "k": k,
              "latency_note": "wall-clock per search on CPU after one untimed warm-up query per mode", "modes": {}}
    for mode in modes:
        if rows:   # warm-up: model loading must not be counted as query latency
            search(SearchRequest(repository_id=repository_id, query=rows[0][0]["query"], mode=mode, top_k=k), embedder, reranker)
        per_query, latencies, returned, verified = [], [], 0, 0
        for query, relevant in rows:
            started = perf_counter()
            response = search(SearchRequest(repository_id=repository_id, query=query["query"], mode=mode, top_k=k), embedder, reranker)
            latencies.append((perf_counter() - started) * 1000)
            ids = [r.unit_id for r in response.results]
            returned += len(response.results)
            verified += sum(r.source_status.value == "verified" for r in response.results)
            per_query.append({"id": query["id"], "rr": reciprocal_rank(ids, relevant), "r1": recall_at_k(ids, relevant, 1),
                              "r5": recall_at_k(ids, relevant, 5), "r10": recall_at_k(ids, relevant, k), "ndcg": ndcg_at_k(ids, relevant, k),
                              "p10": precision_at_k(ids, relevant, k), "tools": response.tool_calls, "iters": response.iterations,
                              "top": response.results[0].qualified_name if response.results else None})
        mean = lambda key: round(statistics.fmean(r[key] for r in per_query), 4)
        report["modes"][mode.value] = {"mrr@10": mean("rr"), "recall@1": mean("r1"), "recall@5": mean("r5"), f"recall@{k}": mean("r10"),
                                       f"ndcg@{k}": mean("ndcg"), f"precision@{k}": mean("p10"),
                                       "latency_ms_p50": round(statistics.median(latencies), 2), "latency_ms_p95": round(_percentile(latencies, 95), 2),
                                       "tool_calls_mean": mean("tools"), "iterations_mean": mean("iters"),
                                       "span_validity": round(verified / returned, 4) if returned else None,
                                       "misses_at_1": [r["id"] for r in per_query if r["r1"] == 0]}
    report["index"] = index_stats(index)
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
        started = perf_counter()
        repository_id = ingest(IngestRequest(source=source)).id
        indexing_seconds = round(perf_counter() - started, 2)
    else:
        indexing_seconds = None
    report = evaluate(repository_id, dataset, [RetrievalMode(m) for m in args.modes])
    report["index"]["indexing_seconds"] = indexing_seconds
    if indexing_seconds is not None:
        report["index"]["indexing_note"] = "includes snapshot copy, parsing, embedding model load and embedding on CPU"
    text = json.dumps(report, indent=2)
    if args.output: args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
