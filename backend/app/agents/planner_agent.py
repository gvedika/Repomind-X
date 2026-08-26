from __future__ import annotations
import re
from pydantic import BaseModel, Field
from app.agents.state import AgentState
from app.core.config import settings
from app.llm.client import LLMClient
from app.llm.prompts import PLANNER_SYSTEM


ALLOWED_TOOLS = {"search_code", "query_repository_graph", "analyze_function", "impact_analysis", "security_scan"}


class ToolCall(BaseModel):
    tool: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    intent: str = ""
    tasks: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    reasoning: str = ""

    @property
    def tools(self) -> list[str]:
        return [call.tool for call in self.tool_calls]


def _candidate_symbol(question: str) -> str | None:
    # Prefer explicit code-style identifiers, e.g. validate_token.
    matches = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", question)
    keywords = {
        "explain", "authentication", "flow", "identify", "components", "affected",
        "if", "changes", "change", "function", "security", "analyze", "impact",
        "what", "would", "be", "the", "and", "or", "of", "to", "in", "on", "for",
    }
    for token in matches:
        if "_" in token and token.lower() not in keywords:
            return token
    return None


def fallback(question: str) -> ExecutionPlan:
    q = question.lower()
    symbol = _candidate_symbol(question)
    calls = [ToolCall(tool="search_code", arguments={"query": question})]
    tasks = ["retrieve relevant repository evidence"]

    if any(x in q for x in ["architecture", "call", "depend", "flow", "break"]):
        calls.append(ToolCall(tool="query_repository_graph", arguments={"graph_query": question}))
        tasks.append("trace structural dependencies")

    if any(x in q for x in ["impact", "change", "break"]) and symbol:
        calls.append(ToolCall(tool="impact_analysis", arguments={"changed_function": symbol}))
        tasks.append("analyze change impact")

    if any(x in q for x in ["function", "validate", "login", "authenticate", "implementation", "explain"]) and symbol:
        calls.append(ToolCall(tool="analyze_function", arguments={"function_name": symbol}))
        tasks.append("inspect the relevant function")

    if any(x in q for x in ["security", "secret", "vulnerability", "token", "password"]):
        calls.append(ToolCall(tool="security_scan", arguments={}))
        tasks.append("perform security analysis")

    unique = []
    seen = set()
    for call in calls:
        if call.tool not in seen:
            unique.append(call)
            seen.add(call.tool)
    return ExecutionPlan(intent="repository_question", tasks=tasks, tool_calls=unique)


def run(state: AgentState) -> dict:
    previous = set(state.get("completed_tools", []))
    if settings.enable_llm_reasoning:
        try:
            result = LLMClient().generate(
                PLANNER_SYSTEM,
                f"User question: {state['question']}\nAlready completed tools: {sorted(previous)}\n"
                "Choose only tools that add evidence. Do not repeat completed tools. "
                "For analyze_function use the exact function_name argument; for impact_analysis use "
                "the exact changed_function argument. Never pass the whole natural-language question "
                "as a function or changed-function name.",
                response_model=ExecutionPlan,
            )
        except Exception:
            result = fallback(state["question"])
    else:
        result = fallback(state["question"])

    calls = [
        call for call in result.tool_calls
        if call.tool in ALLOWED_TOOLS and call.tool not in previous
    ]
    tools = [call.tool for call in calls]
    return {
        "plan": list(dict.fromkeys(list(previous) + tools)),
        "execution_plan": result.model_dump(),
        "pending_tools": tools,
        "pending_tool_calls": [call.model_dump() for call in calls],
        "iterations": state.get("iterations", 0) + 1,
    }
