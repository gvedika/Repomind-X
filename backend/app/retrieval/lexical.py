"""Code-aware BM25: identifiers are split on camelCase/snake_case/dots, symbol fields are up-weighted."""
from __future__ import annotations
import math
import re
from collections import Counter
from app.models.schemas import CodeUnit

_WORD = re.compile(r"[A-Za-z0-9_$]+")
_PART = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with", "is", "are", "be", "by", "it", "this", "that",
             "which", "what", "where", "how", "does", "do", "code", "function", "functions", "method", "file", "files", "from",
             "return", "returns", "const", "let", "var", "new", "if", "else", "async", "await", "export", "import", "def", "self"}
SUFFIXES = ("ations", "ation", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "s")


def stem(token: str) -> str:
    for suffix in SUFFIXES:
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix in {"ies", "ied"} else "")
    return token


def tokenize(text: str) -> list[str]:
    tokens = []
    for word in _WORD.findall(text):
        parts = [p.lower() for p in _PART.findall(word)]
        whole = word.lower().strip("_$")
        if len(parts) > 1 and whole: tokens.append(whole)
        tokens.extend(parts)
    return [stem(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


def unit_tokens(unit: CodeUnit) -> list[str]:
    """Name fields weighted x3, signature/docstring/path x2, body/imports x1."""
    name = tokenize(f"{unit.name} {unit.qualified_name}")
    meta = tokenize(" ".join(filter(None, [unit.signature, unit.docstring, unit.file_path])))
    body = tokenize(" ".join([unit.source, " ".join(unit.imports), " ".join(unit.calls)]))
    return name * 3 + meta * 2 + body


class BM25Index:
    def __init__(self, documents: list[list[str]], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tfs = [Counter(doc) for doc in documents]
        self.lengths = [len(doc) for doc in documents]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        df = Counter(term for tf in self.tfs for term in tf)
        n = len(documents)
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}
        self.postings: dict[str, list[int]] = {}
        for i, tf in enumerate(self.tfs):
            for term in tf: self.postings.setdefault(term, []).append(i)

    def scores(self, query_tokens: list[str]) -> dict[int, float]:
        out: dict[int, float] = {}
        for term in set(query_tokens):
            idf = self.idf.get(term)
            if idf is None: continue
            for i in self.postings[term]:
                tf = self.tfs[i][term]
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avg or 1))
                out[i] = out.get(i, 0.0) + idf * tf * (self.k1 + 1) / norm
        return out
