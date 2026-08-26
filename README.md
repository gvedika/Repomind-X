# RepoMind-X — Agentic Production GraphRAG

RepoMind-X is an evidence-first repository intelligence system that combines Python AST analysis, persistent Neo4j knowledge graphs, BGE/Chroma semantic retrieval, CrossEncoder reranking, MCP tools, and dynamic LangGraph orchestration.

## Architecture

```text
Repository
   │
   ├── AST / static analysis ───────┐
   │                                ▼
   │                         Graph Abstraction
   │                                │
   │                                ▼
   │                             Neo4j
   │
   └── BGE embeddings → ChromaDB → CrossEncoder
                                      │
                                      ▼
User → LangGraph Planner → MCP Client → MCP Server → Repository Tools
                         ↑                         │
                         └──── observations ───────┘
                                      │
                                      ▼
                              LLM reasoning
                                      │
                                      ▼
                               Verification
```

## Production dependencies

- Python 3.11+
- Neo4j 5
- ChromaDB 0.5.x
- MLflow 2.19+
- Prometheus + Grafana
- Node 22+ for the frontend
- An OpenAI, Anthropic, or OpenAI-compatible local LLM for live reasoning

## Quick start

1. Copy `.env.example` to `.env`.
2. Set a strong `NEO4J_PASSWORD`.
3. Configure an LLM provider if live reasoning is required.
4. Start the stack:

```bash
docker compose up --build
```

5. Open the frontend at `http://localhost:5173`.

The supplied sample repository is mounted at `/opt/examples/sample_repo`.

## Runtime behavior

- Local repositories are copied into the configured repository sandbox before indexing.
- Remote Git repositories are cloned into the same sandbox.
- Production graph execution uses Neo4j. The in-memory backend exists only for tests or explicit `GRAPH_BACKEND=memory`.
- Agents communicate with repository tools through the MCP client/server boundary.
- The planner emits typed MCP tool calls with explicit arguments; function/change identifiers are never substituted with the full natural-language question.
- Repository content is treated as untrusted data; repository instructions cannot override system behavior.
- No benchmark numbers are committed without a real benchmark execution.

## Validation status

The repository is hardened around the real MCP client/server boundary and persistent Neo4j/Chroma production paths. The local validation pass covers Python compilation, plain `pytest tests -q`, and MCP client lifecycle code inspection. Full Neo4j, ChromaDB, MLflow, Grafana, Prometheus, Docker, and live LLM validation require the external services and credentials described below; those checks must be reported as **NOT RUN** when the services are unavailable rather than represented by fabricated metrics.

This project is **production-oriented** / has a **production-grade architecture**; it does not claim production readiness solely from the repository contents.

## Evaluation

Create a labelled JSON dataset containing repository questions and gold `relevant_ids`, then run:

```bash
python -m app.evaluation.run_benchmark \
  --repository-id <repository-id> \
  --dataset <dataset.json> \
  --output evaluation_results.json
```

This executes Vector RAG, Graph Retrieval, Hybrid GraphRAG, and Agentic GraphRAG and records Precision@5, Recall@5, MRR, NDCG@5, latency, tool calls, and evidence-grounded measurements. MLflow logging is attempted when `MLFLOW_TRACKING_URI` is configured.

## Tests

From `backend/`:

```bash
pytest tests -q
```

The MCP integration test is intentionally skipped unless `RUN_MCP_INTEGRATION=1` is set and the external services are running.

## Important environment variables

See `.env.example` for the complete configuration surface, including:

- `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
- `CHROMA_HOST`, `CHROMA_PORT`
- `LLM_PROVIDER`, `LLM_MODEL`
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_BASE_URL`
- `EMBEDDING_MODEL`, `RERANKER_MODEL`
- `MLFLOW_TRACKING_URI`
- `MCP_SERVER_COMMAND`
- `MAX_AGENT_ITERATIONS`, `MAX_TOOL_CALLS`

## Security

RepoMind-X validates repository sources and tool arguments, scans for common secrets and dangerous execution patterns, blocks common prompt-injection attempts, prevents repository tool path traversal, and never executes repository code merely because an LLM requests it.
