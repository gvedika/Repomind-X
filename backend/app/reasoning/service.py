from pydantic import BaseModel, Field

class ReasonedAnswer(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    citations: list[str] = []

class ReasoningService:
    def generate(self, question, evidence):
        return ReasonedAnswer(
            answer=f"Analysis for: {question}\nEvidence collected from repository intelligence pipeline.",
            confidence=0.75,
            citations=evidence if isinstance(evidence,list) else []
        )
