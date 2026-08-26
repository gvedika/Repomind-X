from __future__ import annotations
from app.ml.inference import rerank
from app.services.store import store
from app.mcp_server.tools.common import vector
from app.mcp_server.response import tool_response
from app.security.input_validation import validate_tool_string


@tool_response
def search_code(repository_id:str,query:str,language:str|None=None,filters:dict|None=None)->dict:
    query=validate_tool_string(query)
    # Persistent Chroma is the source of truth; process-local store is only a compatibility cache.
    where=dict(filters or {})
    if language: where["language"]=language
    candidates=vector(repository_id).query(query,limit=50,filters=where or None)
    baseline=[{"id":x.id,"snippet":x.text[:1600],"score":x.score,"metadata":x.metadata} for x in candidates[:5]]
    ranked=rerank(query,candidates,limit=5)
    results=[{"id":x.id,"snippet":x.text[:1600],"score":x.score,"metadata":x.metadata} for x in ranked]
    return {"results":results,"vector_results":baseline,"sources":[x["id"] for x in results]}
