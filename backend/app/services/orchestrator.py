from __future__ import annotations
from functools import lru_cache
from app.models.schemas import Evidence,Finding,QueryResponse
from app.services.agent_graph import build_agent_graph
from app.services.store import RepositoryState


@lru_cache(maxsize=1)
def workflow(): return build_agent_graph()


def answer(state:RepositoryState,question:str)->QueryResponse:
    result=workflow().invoke({"repository_id":state.summary.id,"question":question,"completed_tools":[],"tool_observations":{},"iterations":0,"tool_calls":0})
    semantic=result.get("semantic_context",[])
    graph=result.get("graph_context",{})
    function=result.get("function_context",{})
    files=list(dict.fromkeys(item.get("metadata",{}).get("file_path","") for item in semantic if item.get("metadata",{}).get("file_path")))
    functions=list(dict.fromkeys(item.get("metadata",{}).get("function","") for item in semantic if item.get("metadata",{}).get("function")))
    functions += [item.get("name","") for item in function.get("matches",[]) if item.get("name")]
    graph_path=graph.get("path",[])
    evidence=Evidence(files=files,functions=list(dict.fromkeys(functions)),graph_path=graph_path,
                      findings=[Finding.model_validate(item) for item in result.get("security_context",[])])
    return QueryResponse(answer=result.get("answer",""),confidence=result.get("confidence",0.0),
                         plan=result.get("plan",[]),evidence=evidence,verification_notes=result.get("verification_notes",[]))
