"""Bounded, evidence-guided adaptive retrieval.

The loop chooses among a fixed allowlist of typed actions using simple rules over the *user query* and retrieval
scores. Repository text is only ever scored, never interpreted as instructions. Every step is logged with its reason,
candidate counts and duration; the loop stops on sufficiency, no new evidence, or any budget."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import StrEnum
from time import perf_counter
from app.core.config import settings
from app.models.schemas import TraceStep
from app.retrieval.graph import ordered_call_evidence
from app.retrieval.lexical import tokenize


class Action(StrEnum):
    LEXICAL_SEARCH = "lexical"
    SEMANTIC_SEARCH = "semantic"
    FUSE = "rrf"
    EXPAND_RELATIONSHIPS = "graph"
    STRUCTURAL_ORDER = "structural_order"
    QUERY_REWRITE = "semantic_rewrite"
    STOP = "stop"


ALLOWED_ACTIONS = frozenset(Action)
_ORDER = re.compile(r"\b(?:calls?|invokes?|uses?|runs?)\s+[`'\"]?([\w.$]+?)[`'\"]?(?:\(\))?\s+(before|after)\s+[`'\"]?([\w.$]+?)[`'\"]?(?:\(\))?(?=[\s?.,!]|$)", re.I)
_RELATION = re.compile(r"\b(call(?:s|ed|ers?|ing)?|invok\w*|depend\w*|uses?|used by|import\w*|who\s+uses|flows?|pipeline|chain|downstream|upstream)\b", re.I)
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*(?:\.[\w$]+)+|[a-z]+[A-Z][\w$]*|[A-Za-z]+_[\w]+|[\w$]+\(\)")


@dataclass
class Budget:
    max_iterations: int = field(default_factory=lambda: settings.adaptive_max_iterations)
    max_tool_calls: int = field(default_factory=lambda: settings.max_tool_calls)
    max_hops: int = field(default_factory=lambda: settings.graph_max_hops)
    fanout: int = field(default_factory=lambda: settings.graph_fanout)
    max_candidates: int = field(default_factory=lambda: settings.adaptive_max_candidates)
    timeout_s: float = field(default_factory=lambda: settings.adaptive_timeout_seconds)


@dataclass
class AdaptiveOutcome:
    ranked: list[tuple[str, float]]
    relationships: dict[str, list[dict]]
    iterations: int
    stop_reason: str
    structural: list[dict] = field(default_factory=list)


def query_signals(query: str) -> dict:
    order = _ORDER.search(query)
    return {"order": (order.group(1), order.group(2).lower(), order.group(3)) if order else None,
            "relation": bool(_RELATION.search(query)), "identifiers": _IDENTIFIER.findall(query)}


def adaptive_search(pipeline, query: str, top_k: int, budget: Budget | None = None) -> AdaptiveOutcome:
    from app.retrieval.service import reciprocal_rank_fusion
    budget = budget or Budget()
    started = perf_counter()
    index = pipeline.index
    signals = query_signals(query)
    limit = min(max(settings.retrieval_candidates, top_k), budget.max_candidates)
    relationships: dict[str, list[dict]] = {}
    iteration = 0

    def out_of_budget() -> str | None:
        if iteration >= budget.max_iterations: return "iteration_budget"
        if pipeline.tool_calls >= budget.max_tool_calls: return "tool_call_budget"
        if perf_counter() - started > budget.timeout_s: return "timeout"
        return None

    def stop(reason: str, ranked, structural=None) -> AdaptiveOutcome:
        pipeline.trace.append(TraceStep(iteration=len(pipeline.trace) + 1, action=Action.STOP.value, reason=reason,
                                        candidates=len(ranked), duration_ms=0.0))
        return AdaptiveOutcome(ranked[:budget.max_candidates], relationships, iteration, reason, structural or [])

    # Iteration 1: hybrid first stage.
    iteration += 1
    lexical = pipeline.lexical(query, limit, reason="first stage: identifiers and code tokens")
    semantic = pipeline.semantic(query, limit, reason="first stage: behavioral meaning")
    lists = {"lexical": lexical, "semantic": semantic}
    ranked = pipeline.fuse(lists)
    seen = {u for u, _ in ranked}

    # Structural ordering question: answer from call-site facts, keep hybrid results as supporting context.
    if signals["order"] and not out_of_budget():
        iteration += 1
        first, relation, second = signals["order"]
        if relation == "after": first, second = second, first
        step = perf_counter()
        evidence = [e for e in ordered_call_evidence(index.units, first, second)]
        ordered = sorted(evidence, key=lambda e: (e["observed_order"] != "before", e["file_path"], e["qualified_name"]))
        structural_ranked = [(e["unit_id"], 1.0 if e["observed_order"] == "before" else 0.5) for e in ordered]
        pipeline.tool_calls += 1
        for rank, (uid, score) in enumerate(structural_ranked, 1):
            pipeline.components.setdefault(uid, {})["structural"] = score
            pipeline.ranks.setdefault(uid, {})["structural"] = rank
        for e in ordered:
            relationships.setdefault(e["unit_id"], []).append({"type": "CALL_ORDER", **{k: v for k, v in e.items() if k != "unit_id"}})
        pipeline.trace.append(TraceStep(iteration=len(pipeline.trace) + 1, action=Action.STRUCTURAL_ORDER.value,
                                        reason=f"query asks whether {first} is called before {second}; scanning call sites of all units",
                                        candidates=len(ordered), new_candidates=len({u for u, _ in structural_ranked} - seen),
                                        duration_ms=round((perf_counter() - step) * 1000, 2)))
        rest = [(u, s) for u, s in ranked if u not in {x for x, _ in structural_ranked}]
        return stop("structural_answer" if ordered else "no_structural_match", structural_ranked + rest, evidence)

    # Relationship intent: expand the call graph around the strongest candidates.
    if signals["relation"] and not out_of_budget():
        iteration += 1
        step = perf_counter()
        seeds = [u for u, _ in ranked[:3]]
        expanded = index.graph.expand(seeds, max_hops=budget.max_hops, fanout=budget.fanout, limit=budget.max_candidates)
        graph_ranked = [(uid, 1.0 / hop) for uid, _, hop in expanded if uid in index.by_id]
        for uid, edge, hop in expanded:
            relationships.setdefault(uid, []).append({**edge.as_dict({u.unit_id: u for u in index.all_units}), "hops": hop})
            for seed in seeds:
                if seed in (edge.source, edge.target):
                    relationships.setdefault(seed, []).append({**edge.as_dict({u.unit_id: u for u in index.all_units}), "hops": hop})
        pipeline.tool_calls += 1
        for rank, (uid, score) in enumerate(graph_ranked, 1):
            pipeline.components.setdefault(uid, {})["graph"] = score
            pipeline.ranks.setdefault(uid, {})["graph"] = rank
        new = len({u for u, _ in graph_ranked} - seen)
        pipeline.trace.append(TraceStep(iteration=len(pipeline.trace) + 1, action=Action.EXPAND_RELATIONSHIPS.value,
                                        reason=f"relationship intent; expanded CALLS edges from top {len(seeds)} candidates (hops<={budget.max_hops}, fanout<={budget.fanout})",
                                        candidates=len(graph_ranked), new_candidates=new, duration_ms=round((perf_counter() - step) * 1000, 2)))
        if graph_ranked:
            lists["graph"] = graph_ranked
            ranked = pipeline.fuse(lists)
            seen |= {u for u, _ in ranked}

    # Sufficiency: both first-stage signals agree on the top unit.
    agree = bool(lexical and semantic and lexical[0][0] == semantic[0][0])
    if agree and not signals["relation"]:
        return stop("sufficient_evidence: lexical and semantic agree on the top unit", ranked)
    if reason := out_of_budget():
        return stop(reason, ranked)

    # Evidence gap: the two signals disagree — retry semantic retrieval with a keyword-only rewrite of the query.
    rewrite = " ".join(dict.fromkeys(tokenize(query)))
    if rewrite and rewrite != query.lower():
        iteration += 1
        extra = pipeline.semantic(rewrite, limit, reason="evidence gap: lexical/semantic disagree on top unit; keyword-only query rewrite",
                                  seen=seen, name=Action.QUERY_REWRITE.value)
        new = {u for u, _ in extra} - seen
        lists["semantic_rewrite"] = extra
        ranked = pipeline.fuse(lists)
        if not new:
            return stop("no_new_evidence: rewrite only re-ranked existing candidates", ranked)
    return stop("rules_exhausted", ranked)
