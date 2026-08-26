from app.agents.planner_agent import fallback, run
from app.core.config import settings


def test_fallback_uses_structured_function_arguments():
    plan = fallback("Explain authentication flow and identify what is affected if validate_token changes.")
    calls = {call.tool: call.arguments for call in plan.tool_calls}
    assert calls["analyze_function"]["function_name"] == "validate_token"
    assert calls["impact_analysis"]["changed_function"] == "validate_token"


def test_run_preserves_structured_tool_calls(monkeypatch):
    monkeypatch.setattr(settings, "enable_llm_reasoning", False)
    result = run({
        "question": "What changes if validate_token changes?",
        "completed_tools": [],
        "iterations": 0,
    })
    calls = {call["tool"]: call["arguments"] for call in result["pending_tool_calls"]}
    assert calls["impact_analysis"]["changed_function"] == "validate_token"
