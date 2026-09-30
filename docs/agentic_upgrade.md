# RepoMind-X Agentic Production Upgrade (legacy agent path)

> This describes the earlier LangGraph + MCP + Neo4j question-answering path (`POST /api/query`). The Theme 1 retrieval system (`POST /api/search`) is documented in the README and `docs/technical-report.md`, and it does not need Neo4j, Chroma or an LLM. This legacy path was not run in the build environment.

## Implemented architecture

- Repository ingestion copies local repositories into the configured sandbox and clones remote repositories with Git.
- Python AST analysis extracts imports, functions, classes, call relationships, API route candidates, database entities, and framework components.
- Production graph persistence is Neo4j through `GraphBackend`; the in-memory backend is retained only for isolated tests/explicit `GRAPH_BACKEND=memory`.
- Semantic retrieval is persistent ChromaDB with BGE embeddings.
- CrossEncoder reranking is part of the retrieval path and has a reproducible training/evaluation lifecycle.
- Agents use a real MCP client boundary. The LangGraph workflow does not import MCP tool implementations.
- MCP server tools expose structured results and are transported through the MCP Python SDK over stdio.
- Planner output is Pydantic-validated and determines which tools are executed. The graph can loop back to the planner for additional evidence subject to iteration/tool-call limits.
- LLM access is provider-neutral for OpenAI-compatible, Anthropic, and local/OpenAI-compatible endpoints.
- Prometheus metrics are emitted from agent, MCP, graph, vector, embedding, reranking, and LLM execution paths.
- MLflow logging is connected to the training/evaluation lifecycle.
- Prompt-injection, secret detection, path validation, and repository sandboxing are implemented.
- Frontend API calls are proxied through the production Nginx configuration.

## Validation status

Static Python compilation succeeds for the backend source tree. Full runtime validation requires the declared Python dependencies plus running Neo4j, ChromaDB, MLflow, and an available embedding/reranker model; an LLM provider is required for live LLM reasoning. No benchmark values are included unless produced by the executable benchmark runner.
