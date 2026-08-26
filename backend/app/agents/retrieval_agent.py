"""Compatibility node delegating through the real MCP client."""
from app.agents.state import AgentState
from app.mcp_client.client import MCPClient


def run(state:AgentState)->dict:
    return MCPClient().execute("search_code",{"repository_id":state["repository_id"],"query":state["question"]})
