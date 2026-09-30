# RepoMind-X Evaluation Report

Every number here comes from an executed run. The committed files are the source of truth.

| Evaluation | Command (from `backend/`) | Artifact |
|---|---|---|
| Official CoIR Apps Retrieval (MTEB, test split) | `python -m app.evaluation.coir_apps --output ../submission/mteb_results` | `../submission/mteb_results/` (MTEB JSON and run manifest) |
| Custom aligned benchmark, dev split (used for tuning) | `python -m app.evaluation.retrieval_eval --dataset evaluation/dev_sample_js.json` | `evaluation/results/dev_sample_js_modes.json` |
| Custom aligned benchmark, held-out test split | `python -m app.evaluation.retrieval_eval --dataset evaluation/test_sample_js.json` | `../submission/custom_benchmark/test_sample_js_modes.json` |

The custom benchmark ranks the same canonical code units in every mode (semantic, lexical, hybrid, hybrid_rerank,
adaptive) and reports MRR@10, Recall@1/5/10, nDCG@10, median latency and the queries missed at rank 1. Labels are
qualified names, optionally written as `path::qualified_name`. See the README for the current figures and caveats.
