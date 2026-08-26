
from typing import Iterable
class CodeReranker:
    """Inference interface for CrossEncoder/CodeBERT rerankers."""
    def __init__(self, model=None): self.model=model
    def score(self, query, snippets: Iterable[str]):
        if self.model:
            return self.model.predict([(query,s) for s in snippets])
        return [0.0 for _ in snippets]
