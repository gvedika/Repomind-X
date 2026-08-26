from app.mcp_server.tools.common import repository_root
from app.services.security import scan_python
from app.mcp_server.response import tool_response


@tool_response
def security_scan(repository_id:str)->dict:
    findings=scan_python(repository_root(repository_id))
    return {"findings":[f.model_dump() for f in findings],"sources":[f"{f.file_path}:{f.line}" for f in findings]}
