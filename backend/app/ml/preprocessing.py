from __future__ import annotations
import re
from app.ml.dataset import RelevanceExample


def normalize_code(text:str)->str:
    return re.sub(r"\s+"," ",text).strip()


def preprocess(rows):
    return [RelevanceExample(query=r.query.strip(),positive_code=normalize_code(r.positive_code),
                             negative_code=normalize_code(r.negative_code),label=r.label) for r in rows if r.query.strip()]
