from __future__ import annotations
from time import perf_counter
from functools import wraps


def tool_response(fn):
    @wraps(fn)
    def wrapper(*args,**kwargs):
        started=perf_counter()
        try:
            result=fn(*args,**kwargs)
            return {"success":True,"result":result,"sources":result.get("sources",[]) if isinstance(result,dict) else [],
                    "execution_time_ms":round((perf_counter()-started)*1000,2),"error":None,**(result if isinstance(result,dict) else {})}
        except Exception as exc:
            return {"success":False,"result":None,"sources":[],"execution_time_ms":round((perf_counter()-started)*1000,2),"error":str(exc)}
    wrapper.__name__=fn.__name__
    wrapper.__doc__=fn.__doc__
    return wrapper
