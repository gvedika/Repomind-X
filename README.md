# RepoMind-X — Agentic Code Intelligence

**Samsung PRISM GenAI Hackathon 2026 · Theme 1: Agentic Code Intelligence**

Ask a question about a codebase in plain English, and RepoMind-X returns the **actual code that answers it**: a ranked
list of functions, methods, classes and TypeScript types. Every result gives the exact file path and line range, a source
excerpt checked against the indexed code, and the evidence that put it at that rank. It indexes JavaScript and TypeScript
(plus Python) and runs entirely on a CPU laptop. An LLM is optional and never replaces the ranked source evidence.

## Submission at a glance

| | |
|---|---|
| **Official score (CoIR Apps Retrieval, MTEB, test split)** | **nDCG@10 = 0.55088** · Recall@100 = 0.89456 |
| Official result file | [`submission/mteb_results/repomind-x__gte-modernbert-base/repomind-x-encoder-v1/AppsRetrieval.json`](submission/mteb_results/repomind-x__gte-modernbert-base/repomind-x-encoder-v1/AppsRetrieval.json) |
| Run manifest (hardware, versions, command, timing) | [`submission/mteb_results/run_manifest.json`](submission/mteb_results/run_manifest.json) |
| Embedding model | `Alibaba-NLP/gte-modernbert-base`, CPU only |
| Languages indexed | JavaScript (`.js .jsx .mjs .cjs`), TypeScript (`.ts .tsx .mts .cts`), Python |
| Retrieval modes | hybrid (default) · adaptive · semantic · lexical · hybrid + rerank |
| Held-out results (sample repos) | TypeScript: hybrid/adaptive MRR@10 **1.000** · JavaScript: adaptive **0.857**, semantic **0.869** |
| Source-span validity | **100%** of returned results, in every mode and split |
| Search latency (CPU, warm) | about **40 ms** median for hybrid and adaptive |
| Tests | 75 passed, 1 skipped (needs external services) |
| Release tag | `PRISM_GENAI_HACKATHON_Y2026` |

## Why it's different

- **Real code, exact locations.** Results are functions and methods, never whole files or generated prose. Each one
  carries a one-based line range, and before it is shown its excerpt is re-checked against the indexed snapshot.
  Mismatched or moved code is flagged, never silently relocated.
- **It understands behaviour, not just names.** Documents contain the implementation body, so "retry with growing
  delays" finds `withRetry` even though the query never names it.
- **Hybrid by design.** A code-aware BM25 (it splits `camelCase`, `snake_case` and `a.b.c`) is fused with dense
  embeddings using reciprocal rank fusion. Every result shows how each method ranked it.
- **Agentic, but bounded and auditable.** Adaptive mode picks from a fixed set of actions (keyword search, semantic
  search, call-graph expansion, call-order analysis, query rewrite, stop) using simple evidence-gap rules. Each step is
  logged, and hard budgets on iterations, tool calls, graph hops and time guarantee it stops.
- **Honest static analysis.** A call edge is created only when it can be resolved from the code. Dynamic dispatch and
  external libraries are listed as unresolved, not guessed. For "does X run before Y?", results report source order and
  say that it doesn't prove runtime order.
- **Version-aware.** Each Git commit is indexed separately, and results never mix versions.
- **Safe with untrusted code.** Nothing from an indexed repository is executed, and repository text is never
  treated as instructions.

## Example (real output)

Captured from the live API on the bundled `examples/sample_js_repo`.

**Behavioural question, default hybrid mode:** "retry an async operation with growing delays"

```
#1 withRetry               src/utils/retry.cjs:6-17    verified   keyword #1 · meaning #1
#2 chunk                   src/utils/retry.cjs:19-23   verified   keyword #2 · meaning #2
#3 router.post('/orders')  src/routes/orders.js:14-19  verified   keyword #3 · meaning #3
trace: lexical -> semantic -> rrf
```

**Structural question, adaptive mode:** "which handlers call withRetry before chargeCard"

```
#1 router.post('/orders')  src/routes/orders.js:14-19     verified   call order #1 (hybrid alone ranked it #2)
     call order: withRetry (line 17) before chargeCard (line 17)
#2 chargeCard              src/services/payments.mjs:3-11 verified
#3 withRetry               src/utils/retry.cjs:6-17       verified
trace: lexical -> semantic -> rrf -> structural_order -> stop (structural_answer)
warning: call order is syntactic source order within each unit; it does not prove runtime execution order
```

Plain hybrid ranks `chargeCard` first here. Adaptive mode recognises a structural question, inspects call sites, and
promotes the handler that actually makes both calls.

## Quick start (CPU, no Docker)

Requirements: Python 3.12, Node 20+ and about 1.5 GB of disk for the model cache. Tested on Windows 11 with a 16-thread
Intel CPU; nothing is Windows-specific. The first ingest downloads the embedding model (about 600 MB).

**1. Backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate                     # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
GRAPH_BACKEND=memory uvicorn app.main:app --port 8000
# Windows PowerShell: $env:GRAPH_BACKEND="memory"; uvicorn app.main:app --port 8000
```

**2. Frontend** (second terminal)

```bash
cd frontend
npm ci
npm run dev                                   # open http://localhost:5173
```

**3. Try it**

1. Index `../examples/sample_js_repo` or `../examples/sample_ts_repo`. Paths are relative to `backend/`; any local
   folder or public Git URL also works, optionally with a commit.
2. Check the parse-coverage bar: files parsed, partial and skipped, plus code units and languages.
3. Click an example question and press **Search**. Results show `file:line` links, "Ranked by …" evidence, and
   highlighted code with a **Copy** button.
4. Click a result to see its full verified source, what it calls, what calls it, and any calls left unresolved.
5. Switch to **Adaptive** to see the search trace, or tick **compare with baseline** to see two modes side by side.

**Terminal demo.** One command covers ingest, name-free questions, ranked snippets, baseline vs adaptive with trace,
the official score and limitations. Everything it prints comes from live calls.

```bash
cd backend && GRAPH_BACKEND=memory python -m app.demo
```

## How it works

```
                 ┌────────────── ingestion (per Git commit) ───────────────┐
repository ─────►│ Tree-sitter JS/TS · Python ast  ──►  canonical CodeUnits │──► local index (.repomind/)
                 └──────────────────────────────────────────────────────────┘        │
                                                                                    ▼
question ──► lexical (code-aware BM25) ──┐
         └─► semantic (gte, CPU) ────────┴─► RRF fusion ─► [CrossEncoder, optional] ─► source verification ─► ranked units
                    ▲                                                                        ▲
                    └──── adaptive loop: graph expansion · call-order analysis · query rewrite · stop (budgeted, traced)
```

| Component | Where | What it does |
|---|---|---|
| Canonical code units | `backend/app/models/schemas.py`, `app/services/code_units.py` | Every language adapter emits the same record: an ID scoped to repository and commit, type, names, signature, one-based span, real source body, docstring, imports, ordered call sites, exports and parse status |
| JS/TS adapters | `app/services/js_analyzer.py` | Tree-sitter extraction of functions, arrow functions, class and object methods, prototype methods, route handlers (`router.post('/orders')`), ESM/CommonJS imports and exports, and JSDoc. TypeScript adds interfaces, type aliases, enums, namespaces and abstract classes. Malformed files are recovered chunk by chunk; vendor, build, bundle, binary and `.d.ts` files are skipped with reasons |
| Python adapter | `app/services/analyzer.py` | `ast`-based extraction into the same schema |
| Index and retrieval | `app/retrieval/` | Documents contain the code body. Embeddings are cached per commit. Code-aware BM25 and RRF (k=60) fusion; exact ties go to semantic rank. The optional CrossEncoder only sees a bounded pool of 30 |
| Source verification | `app/retrieval/source.py` | Checks repository and commit identity, path containment, file existence, span bounds and content match |
| Static code graph | `app/retrieval/graph.py` | Conservative CONTAINS, DEFINES, EXPORTS, IMPORTS and CALLS edges; unresolved calls are kept with reasons |
| Adaptive retrieval | `app/retrieval/adaptive.py` | Allowlisted actions, evidence-gap rules and budgets (4 iterations, 12 tool calls, 100 candidates, 2 hops, fan-out 8, 10 s); every stop reason is explicit |
| API | `app/main.py` | `POST /api/search`, ingest, commits, unit source |
| UI | `frontend/src/` | Ranked results, mode selector, baseline comparison, trace, coverage and source viewer |

## Evaluation

### Official: CoIR Apps Retrieval (MTEB)

```bash
cd backend
pip install -r requirements-eval.txt
python -m app.evaluation.coir_apps --output ../submission/mteb_results
```

The encoder is the retriever's own embedder and preprocessing: raw code documents, normalised vectors, 512 tokens, on
CPU. MTEB generates and writes the result file itself; no values were edited or estimated.

| Model | nDCG@10 (main) | Recall@10 | Recall@100 | CPU runtime |
|---|---|---|---|---|
| **Alibaba-NLP/gte-modernbert-base** (submitted) | **0.55088** | 0.69615 | 0.89456 | 81 min |
| BAAI/bge-small-en-v1.5 (earlier baseline) | 0.05545 | 0.08101 | 0.19442 | 17 min |

Both runs: task `AppsRetrieval`, split `test`, dataset `CoIR-Retrieval/apps` at revision `f22508f9…`, MTEB 1.39.7.

> **Model-selection disclosure.** The first version used `bge-small-en-v1.5`. `gte-modernbert-base` was evaluated as a
> single candidate, and the default was switched after seeing both models' scores on this official test split. No
> other models, prompts or settings were tried on it. The gte run wrote to `submission/mteb_candidates/…` (recorded in
> its manifest) and its files were then moved unchanged. The baseline is kept as `run_manifest_bge_small_baseline.json`.

### Custom benchmark (separate from the official score)

Every mode ranks the **same canonical code units** for the same queries on the bundled sample repos. Defaults were
chosen on the JavaScript dev split only; the held-out test splits were never used for tuning.

| MRR@10 | semantic | lexical | hybrid (default) | hybrid + rerank | adaptive |
|---|---|---|---|---|---|
| JavaScript dev (18 queries) | 1.000 | 0.815 | 1.000 | 0.889 | 0.972 |
| **JavaScript held-out (14)** | **0.869** | 0.786 | 0.780 | 0.744 | 0.857 |
| **TypeScript held-out (12)** | 0.958 | 0.944 | **1.000** | 1.000 | **1.000** |

| Held-out split | Hybrid p50 / p95 | Adaptive p50 / p95 | Rerank p50 | Indexing (incl. model load) | Index size | Span validity |
|---|---|---|---|---|---|---|
| JavaScript | 40 / 43 ms | 46 / 78 ms | 359 ms | 9.6 s | 94 KB | 100% |
| TypeScript | 41 / 65 ms | 43 / 73 ms | 614 ms | 11.7 s | 77 KB | 100% |

Each run also records Recall@1/5/10, nDCG@10, Precision@10, mean tool calls and iterations, and the queries missed at
rank 1:
- [`submission/custom_benchmark/test_sample_js_modes.json`](submission/custom_benchmark/test_sample_js_modes.json)
- [`submission/custom_benchmark/test_sample_ts_modes.json`](submission/custom_benchmark/test_sample_ts_modes.json)
- [`backend/evaluation/results/dev_sample_js_modes.json`](backend/evaluation/results/dev_sample_js_modes.json)

To reproduce, run `python -m app.evaluation.retrieval_eval --dataset evaluation/<split>.json`. The fixtures have
18–21 retrievable units, so treat these figures as a sanity check, not a leaderboard.

<details><summary>Notes on these numbers</summary>

- Precision@10 is at most 0.1 because each query has exactly one relevant unit.
- JavaScript held-out hybrid scored 0.816 in an earlier run. Two units tied exactly in RRF, and the tie was broken by a
  commit-hashed ID. Ties now go to the better semantic rank, a rule chosen on the dev split (hybrid dev: 0.972 → 1.000).
  On the held-out split it fixes one query and loses two call-order queries; the split played no part in choosing it.
- The MS MARCO CrossEncoder is not code-specific and did not help on the dev split, so reranking is opt-in.
- Earlier bge-small held-out runs are kept as `*_bge_small_baseline.json`.

</details>

## API

```bash
# Index a local path or public Git URL; optional "commit" (SHA or ref) indexes that exact version.
curl -X POST localhost:8000/api/repositories/ingest -H 'content-type: application/json' \
     -d '{"source": "../examples/sample_ts_repo"}'

# Ranked code units. mode: hybrid (default) | adaptive | semantic | lexical | hybrid_rerank
curl -X POST localhost:8000/api/search -H 'content-type: application/json' \
     -d '{"repository_id": "<id>", "query": "add tax and convert currency for the amount due", "top_k": 5}'
```

Each result includes `qualified_name`, `unit_type`, `language`, `signature`, `file_path`, `line_start`, `line_end`,
`excerpt`, `source_status`, `score`, `score_components`, `component_ranks`, `evidence`, `relationships` and `warnings`.
The response adds `commit_sha`, `trace` (each action with its reason, candidate counts and duration), `latency_ms`,
`iterations`, `tool_calls`, `stop_reason` and parse coverage.

Other endpoints:
- `GET /api/repositories`
- `GET /api/repositories/{id}/commits` and `DELETE /api/repositories/{id}/commits/{sha}`
- `GET /api/repositories/{id}/units/{unit_id}`: full verified source, callers, callees and unresolved calls

## Repository layout

```
backend/app/services/     ingestion, JS/TS and Python analyzers, canonical code units
backend/app/retrieval/    index, BM25, embeddings, RRF, reranker, source verification, code graph, adaptive loop
backend/app/evaluation/   official CoIR/MTEB runner, custom benchmark
backend/app/demo.py       terminal demo
backend/tests/            76 tests (parsers, spans, retrieval modes, graph, adaptive, commits, API, evaluation)
backend/evaluation/       labelled dev / held-out query sets
frontend/src/             retrieval-first React UI
examples/                 sample JavaScript, TypeScript and Python repositories (parsed, never executed)
submission/               official MTEB results + manifests, custom benchmark results
docs/technical-report.md  design and evaluation details
```

## Verification status

| Item | Status |
|---|---|
| JS and TS ingestion, canonical units, parse coverage | **PASS** (tests + live runs) |
| Exact spans and verified excerpts; stale, missing and path-traversal handling | **PASS** |
| All five retrieval modes; adaptive trace and budgets | **PASS** |
| Commit-scoped indexing and retrieval | **PASS** (two-commit Git fixture) |
| `/api/search` contract and error states | **PASS** (tests + live server with the real model) |
| Official CoIR Apps Retrieval run on CPU | **PASS** (genuine MTEB output) |
| Frontend build, and hands-on use in Chrome against the live API | **PASS** |
| Docker Compose full stack (Neo4j, Chroma, MLflow, Prometheus, Grafana) | **NOT RUN** (`docker compose config` validates; not needed for search) |
| Optional LLM explanation / legacy LangGraph + MCP agent path (`/api/query`) | **NOT RUN** (needs Neo4j and an LLM key) |

## Limitations

- **Static analysis only.** Call order is source order within one function, not proven runtime order. Dynamic
  dispatch, computed members and re-exports through variables stay unresolved.
- **Language coverage.** Vue and Svelte single-file components and code embedded in HTML are not parsed. `.d.ts` files
  are skipped. Exports inside a TypeScript namespace are listed by their short name.
- **Import bindings are not tracked.** Cross-file calls resolve through the imported module's exports; a name exported
  by two imported modules is left unresolved.
- **Evaluation scope.** The custom benchmark fixtures are small. The official encoder was selected after seeing its test
  score, as disclosed above. Apps queries are truncated to 512 tokens.
- **Optional services.** Docker Compose and the legacy LLM agent path were not run. The Neo4j graph for that path
  keeps only the latest ingest per repository. Cross-version symbol matching is not implemented.

## Optional services (Docker)

Search needs none of these. `docker compose up --build` starts the backend and frontend together with Neo4j (legacy
agent graph), Chroma 0.5.23 (optional vector store), MLflow, Prometheus and Grafana. Set `NEO4J_PASSWORD` in `.env`
first; [`.env.example`](.env.example) documents every setting. Inside the container, index
`/opt/examples/sample_js_repo`. This stack was not started during development.

## Tests

```bash
cd backend && python -m pytest -q      # 75 passed, 1 skipped
cd frontend && npm run build
```
