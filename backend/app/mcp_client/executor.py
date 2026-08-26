from __future__ import annotations
from time import perf_counter


class MCPExecutor:
    def __init__(self,client): self.client=client
    def execute(self,tool,arguments):
        started=perf_counter()
        try:
            result=self.client.execute(tool,arguments)
            result.setdefault("execution_time_ms",round((perf_counter()-started)*1000,2))
            return result
        except Exception as exc:
            return {"success":False,"result":None,"sources":[],"execution_time_ms":round((perf_counter()-started)*1000,2),"error":str(exc)}
