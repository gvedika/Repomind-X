import os
import pytest

from app.mcp_client.client import MCPClient


@pytest.mark.integration
def test_real_mcp_discovery_and_calls():
    if os.getenv("RUN_MCP_INTEGRATION") != "1":
        pytest.skip("Set RUN_MCP_INTEGRATION=1 with Neo4j/Chroma and an indexed repository.")
    repository_id = os.getenv("REPOSITORY_ID")
    if not repository_id:
        pytest.skip("Set REPOSITORY_ID to an indexed repository for the real MCP integration test.")

    client = MCPClient()
    tools = client.discover()
    names = {item["name"] for item in tools}
    expected = {"search_code", "query_repository_graph", "analyze_function", "impact_analysis", "security_scan"}
    assert expected <= names

    calls = {
        "search_code": {"repository_id": repository_id, "query": "authentication"},
        "query_repository_graph": {"repository_id": repository_id, "graph_query": "authentication"},
        "analyze_function": {"repository_id": repository_id, "function_name": "authenticate"},
        "impact_analysis": {"repository_id": repository_id, "changed_function": "authenticate"},
        "security_scan": {"repository_id": repository_id},
    }
    for tool, arguments in calls.items():
        result = client.execute(tool, arguments)
        assert isinstance(result, dict)
        assert "success" in result
        assert "sources" in result
        assert "execution_time_ms" in result
        assert result["success"] is True, f"{tool} failed: {result.get('error')}"
