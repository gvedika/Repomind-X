from app.agents.state import AgentState
from app.services.store import store


def run(state: AgentState) -> dict:
    summary = store.get(state["repository_id"]).summary
    return {"repository_context": {"name": summary.name, "architecture": summary.architecture, "languages": summary.languages}}
