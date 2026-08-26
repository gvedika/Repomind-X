from __future__ import annotations
import asyncio, json, shlex
from contextlib import asynccontextmanager
from typing import Any
from app.core.config import settings
from app.mcp_client.tool_registry import MCPToolRegistry
from app.monitoring.metrics import MCP_TOOL_CALLS,MCP_TOOL_FAILURES,MCP_LATENCY
from time import perf_counter


class MCPClient:
    """Real MCP protocol client. Agents interact only with this boundary."""
    def __init__(self):
        self.registry=MCPToolRegistry()

    @asynccontextmanager
    async def _session(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        command=shlex.split(settings.mcp_server_command)
        if not command: raise RuntimeError("MCP_SERVER_COMMAND is empty.")
        params=StdioServerParameters(command=command[0],args=command[1:],env=None)
        async with stdio_client(params) as (read_stream,write_stream):
            async with ClientSession(read_stream,write_stream) as session:
                await session.initialize()
                tools=await session.list_tools()
                self.registry.update(tools.tools)
                yield session

    async def _execute(self,tool:str,arguments:dict[str,Any])->dict:
        async with self._session() as session:
            if tool not in self.registry:
                raise ValueError(f"MCP server does not expose tool: {tool}")
            schema=self.registry.schema(tool)
            # Server remains authoritative; schema is used as a client-side guard.
            self.registry.validate(tool,arguments)
            result=await asyncio.wait_for(session.call_tool(tool,arguments=arguments),timeout=settings.mcp_timeout_seconds)
            structured=getattr(result,"structuredContent",None) or getattr(result,"structured_content",None)
            if structured is not None:return structured
            content=getattr(result,"content",[]) or []
            text=" ".join(getattr(item,"text",str(item)) for item in content)
            try:return json.loads(text)
            except json.JSONDecodeError:return {"success":False,"result":text,"sources":[],"execution_time_ms":0,"error":"Non-JSON MCP response"}

    def discover(self)->list[dict]:
        async def run():
            async with self._session():
                return self.registry.schemas()
        return asyncio.run(run())

    def execute(self,tool:str,arguments:dict[str,Any])->dict:
        started=perf_counter(); MCP_TOOL_CALLS.labels(tool).inc()
        try:
            result=asyncio.run(self._execute(tool,arguments))
            if result.get("success") is False: MCP_TOOL_FAILURES.labels(tool).inc()
            return result
        except Exception:
            MCP_TOOL_FAILURES.labels(tool).inc()
            raise
        finally:
            MCP_LATENCY.labels(tool).observe(perf_counter()-started)

    def call(self,tool:str,**kwargs): return self.execute(tool,kwargs)
