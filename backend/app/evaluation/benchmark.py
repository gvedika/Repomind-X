"""Real repository benchmark runner. Results are emitted only after executing the configured system."""
from __future__ import annotations
import json,time
from dataclasses import dataclass,asdict
from pathlib import Path
from app.evaluation.metrics import precision_at_k,recall_at_k,reciprocal_rank,ndcg_at_k
from app.mcp_server.tools.repository_tools import search_code
from app.mcp_server.tools.graph_tools import query_repository_graph
from app.services.orchestrator import answer
from app.services.store import store


@dataclass
class SystemMetrics:
    precision_at_5:float=0.0; recall_at_5:float=0.0; mrr:float=0.0; ndcg_at_5:float=0.0
    latency_ms:float=0.0; tool_calls:float=0.0; evidence_accuracy:float=0.0; hallucination_rate:float=0.0


def _aggregate(rows):
    if not rows:return SystemMetrics()
    n=len(rows)
    return SystemMetrics(**{k:sum(r[k] for r in rows)/n for k in SystemMetrics.__dataclass_fields__})


def run(repository_id:str,dataset_path:Path,system:str="vector")->SystemMetrics:
    data=json.loads(dataset_path.read_text(encoding="utf-8")); out=[]
    state=store.get(repository_id)
    if not state: raise ValueError("Repository must be ingested before benchmark execution.")
    for row in data:
        started=time.perf_counter()
        if system=="vector":
            result=search_code(repository_id,row["query"]); ids=[x["id"] for x in result["results"]]; calls=1
        elif system=="graph":
            result=query_repository_graph(repository_id,row["query"]); ids=result.get("sources",[]); calls=1
        elif system=="hybrid":
            v=search_code(repository_id,row["query"]); g=query_repository_graph(repository_id,row["query"])
            ids=[x["id"] for x in v["results"]]+g.get("sources",[]); calls=2
        elif system=="agentic":
            response=answer(state,row["query"]); ids=[f for f in response.evidence.files]; calls=len(response.plan)
        else: raise ValueError(f"Unknown benchmark system: {system}")
        relevant=set(row.get("relevant_ids",[]))
        expected=set(row.get("expected_evidence",[]))
        evidence=set(ids)
        evidence_accuracy=len(evidence&expected)/len(expected) if expected else 0.0
        hallucination=0.0 if not evidence else max(0.0,1.0-len(evidence&expected)/len(evidence)) if expected else 0.0
        out.append({"precision_at_5":precision_at_k(ids,relevant,5),"recall_at_5":recall_at_k(ids,relevant,5),
                    "mrr":reciprocal_rank(ids,relevant),"ndcg_at_5":ndcg_at_k(ids,relevant,5),
                    "latency_ms":(time.perf_counter()-started)*1000,"tool_calls":calls,
                    "evidence_accuracy":evidence_accuracy,"hallucination_rate":hallucination})
    return _aggregate(out)


def run_all(repository_id:str,dataset_path:Path)->dict:
    return {name:asdict(run(repository_id,dataset_path,name)) for name in ("vector","graph","hybrid","agentic")}
