from pydantic import BaseModel,Field


class AgentResponse(BaseModel):
    answer:str
    evidence:list[str]=Field(default_factory=list)
    confidence:float=Field(ge=0,le=1)
