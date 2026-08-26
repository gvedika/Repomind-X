from prometheus_client import Counter,Histogram,Gauge


AGENT_LATENCY=Histogram("agent_execution_seconds","Agent execution latency",["agent"])
AGENT_ITERATIONS=Counter("agent_iterations_total","Agent planner iterations")
MCP_TOOL_CALLS=Counter("mcp_tool_calls_total","MCP tool calls",["tool"])
MCP_TOOL_FAILURES=Counter("mcp_tool_failures_total","MCP tool failures",["tool"])
MCP_LATENCY=Histogram("mcp_latency_seconds","MCP round-trip latency",["tool"])
GRAPH_QUERY_LATENCY=Histogram("graph_query_latency_seconds","Neo4j graph query latency")
VECTOR_SEARCH_LATENCY=Histogram("vector_search_latency_seconds","Chroma semantic search latency")
EMBEDDING_LATENCY=Histogram("embedding_latency_seconds","Embedding latency")
RERANKING_LATENCY=Histogram("reranking_latency_seconds","CrossEncoder reranking latency")
LLM_LATENCY=Histogram("llm_latency_seconds","LLM latency")
LLM_TOKENS=Counter("llm_tokens_total","LLM token usage")
ANSWER_CONFIDENCE=Gauge("answer_confidence","Latest answer confidence")
# Backwards-compatible aliases.
TOOL_CALLS=MCP_TOOL_CALLS
LLM_RESPONSE_TIME=LLM_LATENCY
RETRIEVAL_ACCURACY=Gauge("retrieval_accuracy","Offline benchmark retrieval accuracy")
