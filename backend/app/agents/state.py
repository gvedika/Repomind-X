from typing import TypedDict


class AgentState(TypedDict,total=False):
    repository_id:str
    question:str
    plan:list[str]
    execution_plan:dict
    completed_tools:list[str]
    pending_tools:list[str]
    tool_observations:dict[str,dict]
    semantic_context:list[dict]
    graph_context:dict
    function_context:dict
    security_context:list[dict]
    answer:str
    confidence:float
    verification_notes:list[str]
    iterations:int
    tool_calls:int
