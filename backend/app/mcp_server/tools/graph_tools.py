from __future__ import annotations
from time import perf_counter
from app.models.schemas import NodeKind
from app.monitoring.metrics import GRAPH_QUERY_LATENCY
from app.mcp_server.tools.common import graph
from app.mcp_server.response import tool_response
from app.security.input_validation import validate_tool_string


@tool_response
def query_repository_graph(repository_id:str,graph_query:str,max_hops:int=4)->dict:
    graph_query=validate_tool_string(graph_query); started=perf_counter(); backend=graph(repository_id)
    matching=[]
    for term in graph_query.split():
        matching.extend(node.id for node in backend.search(repository_id,term,{NodeKind.FUNCTION,NodeKind.CLASS,NodeKind.FILE,NodeKind.API_ENDPOINT}))
    ids=backend.path(repository_id,list(dict.fromkeys(matching))[:4],max_hops)
    data=backend.export(repository_id,max(250,len(ids)))
    by={n["id"]:n for n in data["nodes"]}
    edges=[e for e in data["edges"] if e["source"] in ids and e["target"] in ids]
    GRAPH_QUERY_LATENCY.observe(perf_counter()-started)
    return {"path":[by[i]["name"] for i in ids if i in by],"edges":edges,"sources":ids}


@tool_response
def analyze_function(repository_id:str,function_name:str)->dict:
    function_name=validate_tool_string(function_name); backend=graph(repository_id); nodes=backend.search(repository_id,function_name,{NodeKind.FUNCTION})
    output=[]
    for node in nodes[:10]:
        data=backend.export(repository_id,1000); edges=data["edges"]; by={n["id"]:n for n in data["nodes"]}
        callers=[by[e["source"]]["name"] for e in edges if e["target"]==node.id and e["kind"]=="CALLS" and e["source"] in by]
        callees=[by[e["target"]]["name"] for e in edges if e["source"]==node.id and e["kind"]=="CALLS" and e["target"] in by]
        output.append({"name":node.name,"callers":callers,"callees":callees,"complexity":node.metadata.get("complexity"),
                       "dependencies":node.metadata.get("calls",[]),"file_path":node.metadata.get("file_path")})
    return {"matches":output,"sources":[x["name"] for x in output]}


@tool_response
def impact_analysis(repository_id:str,changed_function:str,max_hops:int=4)->dict:
    changed_function=validate_tool_string(changed_function); backend=graph(repository_id); nodes=backend.impact(repository_id,changed_function,max_hops)
    severity="high" if len(nodes)>8 else "medium" if len(nodes)>3 else "low"
    return {"changed_function":changed_function,"risk_level":severity,"affected_components":[node.model_dump() for node in nodes],
            "sources":[node.id for node in nodes]}
