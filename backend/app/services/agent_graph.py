"""Dynamic LangGraph orchestration using a real MCP client boundary."""
from __future__ import annotations
from time import perf_counter
from langgraph.graph import END,START,StateGraph
from app.agents.state import AgentState
from app.agents import planner_agent,tool_agent,code_reasoning_agent,verification_agent
from app.mcp_client.client import MCPClient
from app.monitoring.metrics import AGENT_LATENCY,AGENT_ITERATIONS
from app.core.config import settings


def build_agent_graph():
    graph=StateGraph(AgentState); client=MCPClient()
    def planner(state):
        started=perf_counter()
        try:
            AGENT_ITERATIONS.inc()
            return planner_agent.run(state)
        finally: AGENT_LATENCY.labels("planner").observe(perf_counter()-started)
    def tool(state):
        started=perf_counter()
        try:return tool_agent.run(state,client)
        finally: AGENT_LATENCY.labels("mcp_tool").observe(perf_counter()-started)
    graph.add_node("planner",planner); graph.add_node("tool",tool); graph.add_node("reasoning",code_reasoning_agent.run); graph.add_node("verification",verification_agent.run)
    graph.add_edge(START,"planner")
    def route(state):
        if state.get("iterations",0)>=settings.max_agent_iterations or state.get("tool_calls",0)>=settings.max_tool_calls: return "reasoning"
        if state.get("pending_tools"): return "tool"
        if len(state.get("completed_tools",[]))>=12: return "reasoning"
        # Planner can add new work after observations.
        return "tool" if state.get("pending_tools") else "reasoning"
    graph.add_conditional_edges("planner",route,{"tool":"tool","reasoning":"reasoning"})
    def after_tool(state):
        if state.get("tool_calls",0)>=settings.max_tool_calls:return "reasoning"
        return "planner"
    graph.add_conditional_edges("tool",after_tool,{"planner":"planner","reasoning":"reasoning"})
    graph.add_edge("reasoning","verification"); graph.add_edge("verification",END)
    return graph.compile()
