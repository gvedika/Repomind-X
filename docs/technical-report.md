# RepoMind-X Technical Report: Theme 1, Agentic Code Intelligence

## Problem

Given a natural-language question about a codebase, return the code that implements the behaviour: a ranked list of
real functions and methods with exact file paths and line ranges, plus the evidence behind each rank. Retrieval quality is the
product. Generated prose is optional and always downstream of the ranked evidence.

## System

1. **Ingestion and versioning.** A local path or Git URL is materialised into a per-commit snapshot. An explicit
   commit is exported with `git archive`. A working tree is labelled with HEAD, or `HEAD-dirty` when it has
   uncommitted changes. Repository IDs derive from the source identity, and unit IDs from
   `(repository, commit, path, type, qualified name, ordinal)`.
2. **Parsing.** Language adapters implement one interface and emit canonical `CodeUnit` records: the Tree-sitter
   JavaScript adapter and the `ast`-based Python adapter. Parse failures are recorded per file (`ok`, `partial`,
   `failed` or `skipped`, with reasons) and never abort a repository. Malformed JavaScript is re-parsed per top-level chunk.
3. **Documents.** Each function, method or class document contains its qualified name, signature, docstring, path and
   the **implementation body**, bounded to 2,400 characters for the encoder.
4. **Retrieval.**
   - *Lexical*: BM25 over code-aware tokens (identifiers split on case, underscores and dots; light stemming; name
     fields ×3, signature, docstring and path ×2, body ×1).
   - *Semantic*: `Alibaba-NLP/gte-modernbert-base` on CPU (no query instruction). `bge-small-en-v1.5` was the earlier
     baseline.
   - *Hybrid*: reciprocal rank fusion (k = 60) of both, deduplicated by unit ID. This is the default.
   - *Hybrid + rerank*: MS MARCO MiniLM CrossEncoder over the top 30, blended with the first stage by RRF. Opt-in.
   - *Adaptive*: a bounded rule-based loop over allowlisted actions (below).
5. **Verification.** Before a result is returned, its repository and commit, path containment, file existence, span
   bounds and content equality with the indexed snapshot are checked. Invalid or missing units are dropped with a
   warning, and stale ones are flagged.
6. **Static graph.** CONTAINS, DEFINES, EXPORTS, IMPORTS (module specifiers resolved to repository files) and CALLS.
   A call is linked only when it resolves through lexical scope, `this.` inside a class, an export of an imported
   repository module, or an exact qualified name. Everything else is kept as an unresolved call with a reason.

### Adaptive retrieval

| Signal (from the user query and retrieval scores only) | Action |
|---|---|
| always | lexical + semantic first stage, then RRF |
| "call/invoke/use X before/after Y" | `structural_order`: every unit containing both calls, with line numbers and observed source order; stop |
| relationship words (calls, callers, uses, imports, depends, flow) | `graph`: expand CALLS edges from the top 3 candidates (≤ 2 hops, fan-out ≤ 8), then fuse |
| lexical and semantic agree on the top unit | stop: `sufficient_evidence` |
| they disagree | `semantic_rewrite` with a keyword-only query, then fuse; stop if nothing new |

Hard limits: 4 iterations, 12 tool calls, 100 candidates and a 10-second timeout. Every step is logged with its reason,
candidate and new-candidate counts, and duration. Text from the repository is only ever scored; it is never read as
instructions (see `test_repository_text_is_not_treated_as_instructions`).

## Evaluation

**Official (CoIR Apps Retrieval via MTEB 1.39.7, test split, CPU).** The encoder is the retriever's own embedder and
preprocessing, and MTEB generated the result. With `gte-modernbert-base`: nDCG@10 = **0.55088**, recall@100 = 0.89456,
4,861 s on a 16-thread Intel CPU. The earlier `bge-small-en-v1.5` baseline scored nDCG@10 = 0.05545. Artifacts are in
`submission/mteb_results/`. Disclosure: the default model was switched after seeing both models' scores on this test
split. It was a single candidate, and no other models or settings were tried on the test split.

**Custom (aligned).** Every mode ranks the same canonical units of `examples/sample_js_repo`, which has 21 retrievable
units. Defaults were chosen on an 18-query dev split: semantic 1.00 MRR@10, hybrid 0.97, lexical 0.81, rerank 0.86. The
held-out 14-query test split, with gte-modernbert-base: semantic 0.869, adaptive 0.857, hybrid+rerank 0.851,
hybrid 0.816, lexical 0.786. The bge-small baseline scored 0.780 / 0.854 / 0.744 / 0.746 / 0.786 in the same order.
At this size the figures are indicative only.

## Limitations

The analysis is static: call order is syntactic, not runtime order. TypeScript and other languages are not parsed.
Import binding names are not tracked. The reranker is not code-specific. Cross-version symbol matching is not
implemented. The legacy Neo4j/LangGraph/MCP agent path (`/api/query`) and the Docker Compose stack were not run in the
build environment.
