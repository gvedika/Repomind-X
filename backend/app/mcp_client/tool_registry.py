from __future__ import annotations
from typing import Any
from pydantic import TypeAdapter, ValidationError


class MCPToolRegistry:
    def __init__(self): self.tools={}

    def update(self,tools):
        self.tools={tool.name:tool for tool in tools}

    def names(self): return list(self.tools)

    def schema(self,name):
        if name not in self.tools: raise ValueError(f"Unknown MCP tool: {name}")
        return getattr(self.tools[name],"inputSchema",None) or getattr(self.tools[name],"input_schema",None)

    def schemas(self):
        return [{"name":n,"description":getattr(t,"description",""),"input_schema":self.schema(n)} for n,t in self.tools.items()]

    def validate(self,name,arguments:dict[str,Any]):
        schema=self.schema(name)
        if not schema:return
        required=schema.get("required",[]) if isinstance(schema,dict) else []
        missing=[key for key in required if key not in arguments]
        if missing: raise ValueError(f"Missing MCP arguments for {name}: {missing}")
        # MCP server performs final validation; reject unknown obviously malformed argument containers here.
        if not isinstance(arguments,dict): raise ValueError("MCP arguments must be an object.")
