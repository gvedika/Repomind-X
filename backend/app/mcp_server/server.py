"""RepoMind-X MCP server. Run as `python -m app.mcp_server.server`."""
from mcp.server.fastmcp import FastMCP
from app.mcp_server.tools.graph_tools import analyze_function,impact_analysis,query_repository_graph
from app.mcp_server.tools.repository_tools import search_code
from app.mcp_server.tools.security_tools import security_scan


mcp=FastMCP("RepoMind-X")
mcp.tool()(search_code); mcp.tool()(query_repository_graph); mcp.tool()(analyze_function)
mcp.tool()(impact_analysis); mcp.tool()(security_scan)


if __name__=="__main__":
    mcp.run()
