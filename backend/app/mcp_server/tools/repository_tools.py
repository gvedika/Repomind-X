from __future__ import annotations
from app.models.schemas import RetrievalMode, SearchRequest
from app.retrieval.service import search
from app.mcp_server.response import tool_response
from app.security.input_validation import validate_tool_string

DEFAULT_MODE = RetrievalMode.HYBRID


@tool_response
def search_code(repository_id:str,query:str,language:str|None=None,filters:dict|None=None,mode:str|None=None,top_k:int=5,commit_sha:str|None=None)->dict:
    """Ranked, source-verified code units. `filters` is accepted for backward compatibility; language/commit scope the index."""
    query=validate_tool_string(query)
    response=search(SearchRequest(repository_id=repository_id,query=query,mode=RetrievalMode(mode) if mode else DEFAULT_MODE,
                                  top_k=top_k,commit_sha=commit_sha,language=language))
    results=[{"id":r.unit_id,"snippet":r.excerpt,"score":r.score,
              "metadata":{"repository_id":response.repository_id,"commit_sha":response.commit_sha,"file_path":r.file_path,
                          "function":r.qualified_name,"entity_type":r.unit_type.value,"language":r.language,
                          "line_start":r.line_start,"line_end":r.line_end,"source_status":r.source_status.value},
              "score_components":r.score_components,"component_ranks":r.component_ranks} for r in response.results]
    return {"results":results,"sources":[x["id"] for x in results],"mode":response.mode.value,"warnings":response.warnings,"trace":[t.model_dump() for t in response.trace]}
