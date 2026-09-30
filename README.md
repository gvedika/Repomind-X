# RepoMind-X — Agentic Code Intelligence (Samsung PRISM GenAI Hackathon, Theme 1)

RepoMind-X takes a natural-language question about a repository and returns a **ranked list of real code units** —
functions, methods, classes and TypeScript types — each with its repository-relative path, exact one-based line range, a source excerpt
verified against the indexed snapshot, and the evidence behind its rank. It is JavaScript/TypeScript-first (Tree-sitter)
and keeps a Python adapter. Retrieval runs entirely on CPU; an LLM is optional and never replaces the ranked source evidence.

```
question ──► lexical (code-aware BM25) ─┐
         ├─► semantic (gte, CPU) ───────┼─► RRF fusion ─► [optional CrossEncoder] ─► source verification ─► ranked units
         └─► adaptive loop: graph expansion over static CALLS/IMPORTS/EXPORTS, call-order analysis, query rewrite, stop
```

## What is verified (and what is not)

| Item | Status | Evidence |
|---|---|---|
| JavaScript ingestion (`.js/.jsx/.mjs/.cjs`), canonical units, parse coverage | **PASS** | `backend/tests/test_js_analyzer.py`, live run below |
| TypeScript ingestion (`.ts/.tsx/.mts/.cts`; interfaces, types, enums, namespaces, abstract classes) | **PASS** | `backend/tests/test_ts_analyzer.py`, `examples/sample_ts_repo` |
| Exact spans + verified excerpts, stale/missing/traversal handling | **PASS** | `backend/tests/test_retrieval_sources.py` |
| Semantic / lexical / hybrid / hybrid+rerank / adaptive modes | **PASS** | `backend/tests/test_hybrid_retrieval.py`, `test_graph_adaptive.py` |
| Commit-scoped indexing and retrieval | **PASS** | `backend/tests/test_commit_scope.py` (two-commit Git fixture) |
| `/api/search` contract, errors, partial-parse warnings | **PASS** | `backend/tests/test_search_api.py`; live uvicorn + real embedding model |
| Official CoIR Apps Retrieval (MTEB) run on CPU | **PASS (genuine run)** | `submission/mteb_results/` — nDCG@10 **0.55088** |
| Frontend type-check + production build | **PASS** | `npm run build` |
| Frontend interaction in a browser | **PASS** (checked by hand in Chrome against the live API) | ingest, search, source modal |
| Docker Compose full stack (Neo4j, Chroma, MLflow, Prometheus, Grafana) | **NOT RUN** (`docker compose config` validates) | — |
| LLM explanation / legacy LangGraph + MCP agent path (`/api/query`) | **NOT RUN** (needs Neo4j + an LLM key) | — |

Backend test suite: `75 passed, 1 skipped` (the skipped test needs external services).

## Quick start (CPU, no Docker)

Requirements: Python 3.12, Node 20+ (tested with Node 24), ~1 GB disk for the embedding model cache. Tested on
Windows 11 with a 16-thread Intel CPU; nothing is Windows-specific.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU wheel, avoids CUDA downloads
pip install -r requirements.txt
GRAPH_BACKEND=memory uvicorn app.main:app --port 8000               # PowerShell: $env:GRAPH_BACKEND="memory"; uvicorn app.main:app --port 8000
```

In a second terminal:

```bash
cd frontend
npm ci
npm run dev          # http://localhost:5173 (proxies /api to :8000)
```

In the UI, index `../examples/sample_js_repo` (the path is relative to the backend's working directory), then try the
example questions. The first ingest downloads `Alibaba-NLP/gte-modernbert-base` (~600 MB).

Terminal demo (ingest, name-free questions, ranked snippets, baseline vs adaptive with trace, evaluation result,
limitations; everything printed comes from live calls):

```bash
cd backend && GRAPH_BACKEND=memory python -m app.demo
```

Environment variables are documented in [.env.example](.env.example). Only `REPOSITORY_ROOT`, `GRAPH_BACKEND`,
`MODEL_DEVICE` and the model names matter for retrieval; Neo4j, Chroma, MLflow and LLM settings are optional.

## API

```bash
# Index a local path or public Git URL; optional "commit" (SHA/ref) indexes that exact version.
curl -X POST localhost:8000/api/repositories/ingest -H 'content-type: application/json' \
     -d '{"source": "../examples/sample_js_repo"}'

# Ranked code units. mode: hybrid (default) | adaptive | semantic | lexical | hybrid_rerank
curl -X POST localhost:8000/api/search -H 'content-type: application/json' \
     -d '{"repository_id": "<id>", "query": "retry an async operation with growing delays", "mode": "hybrid", "top_k": 5}'
```

Each result carries `unit_id`, `qualified_name`, `unit_type`, `language`, `signature`, `file_path`, `line_start`,
`line_end`, `excerpt` (bounded; `excerpt_truncated` / `excerpt_line_end` when cut), `source_status`
(`verified` | `stale`), `score`, `score_components` and `component_ranks` (lexical / semantic / rrf / reranker / graph /
structural), `evidence`, `relationships` and `warnings`. The response adds `commit_sha`, `trace` (every action with reason,
candidate counts and duration), `latency_ms`, `iterations`, `tool_calls`, `stop_reason`, parse coverage and warnings.

Other endpoints: `GET /api/repositories`, `GET /api/repositories/{id}/commits`,
`DELETE /api/repositories/{id}/commits/{sha}`, `GET /api/repositories/{id}/units/{unit_id}` (full verified source,
resolved callers/callees and unresolved calls).

Measured on the sample repo with the real embedding model on CPU (warm): hybrid ≈ 40 ms, adaptive ≈ 45 ms (median over the benchmark queries).
The first query after start-up also loads the model (several seconds).

## How it works

- **Canonical code units** (`backend/app/models/schemas.py`, `app/services/code_units.py`): every adapter emits the
  same record: stable ID scoped to repository + commit, type, names, signature, one-based span, real source body,
  docstring, imports, calls with source-ordered call sites, exports, parse status and parser uncertainty.
- **JavaScript/TypeScript adapters** (`app/services/js_analyzer.py`, Tree-sitter): declarations, nameable arrow/function
  expressions, class methods and field arrows, object-literal methods, prototype methods, ESM/CommonJS imports and
  exports, JSDoc, and inline route handlers such as `router.post('/orders')`, named after their call site. Malformed files are
  marked partial and re-parsed per top-level chunk so later definitions survive. `node_modules`, build output, bundles,
  binaries and oversized files are skipped, and the reason is recorded. The TypeScript adapter reuses the same walker
  with the TypeScript/TSX grammars and adds interfaces, type aliases and enums (unit type `type`), namespaces,
  abstract classes and TypeScript class fields. Overload and abstract signatures have no body and are not emitted;
  `.d.ts` declaration files are skipped. Imports resolve to `.ts`/`.tsx` files, including ESM-style `./x.js` → `x.ts`.
- **Index** (`app/retrieval/`): documents contain the implementation body. Embedding vectors are cached per commit in
  `.repomind/embeddings.npz`; lexical search is a code-aware BM25 that splits camelCase, snake_case and dotted identifiers.
  Results are fused with RRF (k=60); exact ties go to the better semantic rank, the strongest signal on the dev split,
  so ordering never depends on hashed IDs. The optional CrossEncoder reranks only a bounded pool (30).
- **Source verification** (`app/retrieval/source.py`): checks repository/commit identity, path containment, file
  existence, span bounds and content match. Invalid or missing units are dropped with a warning; stale units are
  flagged, never silently relocated.
- **Static graph** (`app/retrieval/graph.py`): CONTAINS, DEFINES, EXPORTS, IMPORTS and CALLS. A call becomes an edge
  only when it resolves through nested, enclosing or same-file scope, `this.` methods, an export of an imported
  repository module, or an exact qualified name. Dynamic receivers, external libraries and ambiguous names are listed as
  unresolved.
- **Adaptive mode** (`app/retrieval/adaptive.py`): allowlisted actions (lexical, semantic, rrf, graph expansion,
  structural call order, keyword rewrite, stop). Rules read only the user query and retrieval scores, never repository
  text. Budgets cover iterations (4), tool calls (12), candidates (100), hops (2), fan-out (8) and a 10 s timeout, and
  every stop reason is explicit. For "which functions call X before Y?", it reports the units that contain both calls,
  with their line numbers and observed source order.
- **Commit scope**: an explicit commit is exported with `git archive` into its own snapshot. The working tree is
  labelled with HEAD, plus `-dirty` if it differs. IDs, indexes, Chroma collections and store entries are all
  namespaced by repository + commit.

## Evaluation

### Official screening artifact: CoIR Apps Retrieval (MTEB)

```bash
cd backend
pip install -r requirements-eval.txt
python -m app.evaluation.coir_apps --output ../submission/mteb_results
```

The encoder wraps the same embedder and preprocessing the retriever uses: the configured query instruction (none for
gte), raw code documents, normalised vectors, 512 tokens, CPU. MTEB writes the result file itself.

| Task | Split | Dataset revision | Model | nDCG@10 (main) | Recall@100 | Runtime |
|---|---|---|---|---|---|---|
| AppsRetrieval | test | `f22508f9…` | **Alibaba-NLP/gte-modernbert-base** (CPU, submitted) | **0.55088** | 0.89456 | 4861 s |
| AppsRetrieval | test | `f22508f9…` | BAAI/bge-small-en-v1.5 (CPU, earlier baseline) | 0.05545 | 0.19442 | 995 s |

- Submitted result: `submission/mteb_results/repomind-x__gte-modernbert-base/repomind-x-encoder-v1/AppsRetrieval.json`,
  manifest `submission/mteb_results/run_manifest.json`. The run wrote to `submission/mteb_candidates/…`, as the
  manifest's `command` field records; the files were then moved unchanged.
- Baseline: `submission/mteb_results/repomind-x__bge-small-en-v1.5/…`, manifest `run_manifest_bge_small_baseline.json`.

**Model-selection disclosure.** The first release used `bge-small-en-v1.5`. `gte-modernbert-base` was then run as a
single candidate, and the default was switched *after* seeing both models' scores on this official test split. No other
models, prompts or settings were tried on it. On our own dev split, the switch keeps semantic MRR@10 at 1.000 and lifts
hybrid+rerank from 0.861 to 0.944 (at the time of the switch). Both official results are genuine, unedited MTEB output.

### Custom benchmark (separate from the official artifact)

`python -m app.evaluation.retrieval_eval --dataset evaluation/<split>.json` ingests the fixture and evaluates every mode
on the **same canonical units** for the same queries. Mode defaults were chosen on the dev split only; the held-out
test split is run after each model change and never used for tuning.

| MRR@10 (queries) | semantic | lexical | hybrid | hybrid+rerank | adaptive |
|---|---|---|---|---|---|
| JS dev (18) | 1.000 | 0.815 | 1.000 | 0.889 | 0.972 |
| **JS held-out test (14)** | **0.869** | 0.786 | 0.780 | 0.744 | 0.857 |
| **TS held-out test (12)** | 0.958 | 0.944 | **1.000** | 1.000 | **1.000** |
| JS held-out, earlier bge-small baseline | 0.780 | 0.786 | 0.746 | 0.744 | 0.854 |

Each run also reports Recall@1/5/10, nDCG@10, Precision@10, p50/p95 latency (after one untimed warm-up), mean tool calls
and iterations, **span validity**, and index size and indexing time. Precision@10 is at most 0.1 here, because each query
has a single relevant unit. For every mode and split, span validity is **1.0**: every returned result's excerpt matched
the indexed source.

| Split | Hybrid p50 / p95 | Adaptive p50 / p95 | Rerank p50 | Indexing (incl. model load) | Index size |
|---|---|---|---|---|---|
| JS test | 40 / 43 ms | 46 / 78 ms | 359 ms | 9.6 s | 94 KB |
| TS test | 41 / 65 ms | 43 / 73 ms | 614 ms | 11.7 s | 77 KB |

Sources: `backend/evaluation/results/dev_sample_js_modes.json`,
`submission/custom_benchmark/test_sample_js_modes.json` and `submission/custom_benchmark/test_sample_ts_modes.json`.
The `*_bge_small_baseline.json` files hold the earlier runs. Hybrid remains the default, as chosen on the dev split.

**Note on JS held-out hybrid (0.780).** An earlier run scored 0.816 because two units tied exactly in RRF and the tie was
broken by a commit-hashed ID. The tie-break now prefers semantic rank, chosen from the dev split, where hybrid moved from
0.972 to 1.000. That fixes one held-out query and loses two call-order queries. The held-out split was not used to pick
the rule. The fixtures have 18–21 retrievable units, so treat these figures as a sanity check, not a leaderboard.

## Optional services

`docker compose up --build` starts the backend, frontend, Neo4j, Chroma 0.5.23, MLflow, Prometheus and Grafana (set
`NEO4J_PASSWORD` in `.env` first). None of them are needed for `/api/search`:

- **Neo4j** holds the legacy knowledge graph for the MCP/LangGraph agent path.
- **Chroma** receives body-enriched documents when `CHROMA_HOST` is set.
- **MLflow, Prometheus and Grafana** provide tracking and monitoring.

The compose stack has not been started in the build environment (**NOT RUN**).

## Limitations

- Static analysis only. Call order is syntactic order within one unit, not runtime order across branches, loops,
  callbacks or async code. Dynamic dispatch, computed members and re-exports through variables stay unresolved.
- Vue/Svelte single-file components and code inside HTML are not parsed. `.d.ts` declaration files are skipped.
  Exports declared inside a TypeScript namespace are listed by their short name at file level. The recovery pass for malformed files is heuristic (it splits at column-0 declarations).
- Import binding names are not tracked. Cross-file resolution relies on the imported module exporting the called
  name, and a name exported by two imported modules is left unresolved.
- The MS MARCO CrossEncoder did not help on code in the dev split, so reranking is opt-in.
- The Neo4j graph for the legacy agent path keeps one graph per repository (latest ingest). Commit-scoped retrieval uses
  the per-commit local graph. Cross-version symbol matching is not implemented.
- The encoder was chosen after seeing its official test score (see the disclosure above). It is a 149M-parameter model
  on CPU, and Apps queries are long problem statements truncated to 512 tokens.

## Tests

```bash
cd backend && python -m pytest -q        # 75 passed, 1 skipped
cd frontend && npm run build
```

Repository contents are treated as untrusted data: nothing from an indexed repository is executed, and repository text
is never interpreted as instructions.
