# RepoMind-X Evaluation Report

No benchmark numbers are committed here. This repository contains the executable benchmark runner in `app.evaluation.run_benchmark`.

To produce a real report:

1. Ingest a repository.
2. Prepare a labelled JSON dataset with `query`, `relevant_ids`, and optionally `expected_evidence`.
3. Run `python -m app.evaluation.run_benchmark --repository-id <id> --dataset <file> --output evaluation_results.json`.
4. The runner executes Vector RAG, Graph Retrieval, Hybrid GraphRAG, and Agentic GraphRAG and writes the measured metrics.
5. MLflow logging is attempted using the configured tracking URI; an unavailable MLflow service is reported rather than silently converting the experiment into fake results.

Reported retrieval metrics are Precision@5, Recall@5, MRR, and NDCG@5. System measurements include latency and tool calls; evidence accuracy and a grounded-evidence hallucination proxy are computed only from labelled evidence.
