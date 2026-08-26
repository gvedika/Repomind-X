from app.agents.state import AgentState


def run(state: AgentState) -> dict:
    return {"documentation": {"summary": state.get("answer", ""), "graph_path": state.get("graph_context", {}).get("path", [])}}
