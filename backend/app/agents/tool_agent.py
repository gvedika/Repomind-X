from __future__ import annotations
from app.agents.state import AgentState
from app.mcp_client.client import MCPClient


def run(state: AgentState, client: MCPClient) -> dict:
    pending = state.get("pending_tools", [])
    calls = state.get("pending_tool_calls", [])
    if not pending:
        return {}

    tool = pending[0]
    call = calls[0] if calls else {"tool": tool, "arguments": {"repository_id": state["repository_id"]}}
    arguments = dict(call.get("arguments") or {})
    arguments["repository_id"] = state["repository_id"]

    # The planner owns semantic argument selection. This boundary deliberately
    # does not substitute the full user question for identifier arguments.
    result = client.execute(tool, arguments)

    observations = dict(state.get("tool_observations", {}))
    observations[tool] = result
    completed = state.get("completed_tools", []) + [tool]
    return {
        "tool_observations": observations,
        "completed_tools": completed,
        "pending_tools": pending[1:],
        "pending_tool_calls": calls[1:],
        "tool_calls": state.get("tool_calls", 0) + 1,
        "semantic_context": result.get("results", state.get("semantic_context", []))
        if tool == "search_code" else state.get("semantic_context", []),
        "graph_context": result
        if tool in {"query_repository_graph", "impact_analysis"} else state.get("graph_context", {}),
        "function_context": result
        if tool == "analyze_function" else state.get("function_context", {}),
        "security_context": result.get("findings", [])
        if tool == "security_scan" else state.get("security_context", []),
    }
