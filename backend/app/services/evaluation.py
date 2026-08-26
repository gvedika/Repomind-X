from dataclasses import dataclass


@dataclass
class EvaluationMetrics:
    retrieval_accuracy: float
    dependency_accuracy: float
    explanation_correctness: float
    citation_accuracy: float

    @property
    def rus(self) -> float:
        return round(0.3 * self.retrieval_accuracy + 0.3 * self.dependency_accuracy + 0.2 * self.explanation_correctness + 0.2 * self.citation_accuracy, 4)
