from __future__ import annotations
import json, random
from pathlib import Path
from pydantic import BaseModel


class RelevanceExample(BaseModel):
    query:str
    positive_code:str
    negative_code:str
    label:float=1.0


def load_jsonl(path:Path)->list[RelevanceExample]:
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip(): rows.append(RelevanceExample.model_validate(json.loads(line)))
    return rows


def save_jsonl(rows:list[RelevanceExample],path:Path):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("\n".join(json.dumps(r.model_dump()) for r in rows)+"\n",encoding="utf-8")


def split_dataset(rows,train_ratio=.8,val_ratio=.1,seed=42):
    rows=list(rows); random.Random(seed).shuffle(rows)
    n=len(rows); a=int(n*train_ratio); b=a+int(n*val_ratio)
    return rows[:a],rows[a:b],rows[b:]
