from app.agents.state import AgentState
from app.monitoring.metrics import ANSWER_CONFIDENCE


def run(state:AgentState)->dict:
    notes=[]
    if not state.get("semantic_context"): notes.append("No semantic code citation was resolved.")
    if not state.get("graph_context",{}).get("path"): notes.append("No structural graph path was resolved.")
    if state.get("security_context"): notes.append("Security findings were included as repository evidence.")
    confidence=round(min(0.98,float(state.get("confidence",0.0))),2)
    if notes and confidence>0.75: confidence=0.75
    ANSWER_CONFIDENCE.set(confidence)
    return {"verification_notes":notes or ["Evidence was returned from MCP-backed repository tools."],"confidence":confidence}
