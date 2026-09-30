"""Reproducible terminal demo: python -m app.demo [--source PATH]

1. Ingest a JavaScript repository and show parse coverage.
2. Ask behavioural questions that do not name the target function.
3. Print ranked snippets with exact locations.
4. Compare baseline (hybrid) with adaptive retrieval, including the trace.
5. Show the committed official evaluation result and measured latency.
6. Print the known limitations.
Everything printed comes from live calls; nothing is canned."""
from __future__ import annotations
import torch  # noqa: F401  (Windows DLL order, see app.evaluation.coir_apps)
import argparse
import json
from pathlib import Path
from app.models.schemas import IngestRequest, SearchRequest
from app.retrieval.service import search
from app.services.ingestion import ingest

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ["retry an async operation with growing delays between attempts",
             "compare two digests without leaking timing information",
             "which handlers call withRetry before chargeCard"]


def show(response, limit=3):
    print(f"  mode={response.mode.value} latency={response.latency_ms:.0f}ms tool_calls={response.tool_calls} "
          f"iterations={response.iterations} stop={response.stop_reason}")
    for r in response.results[:limit]:
        print(f"   #{r.rank} {r.qualified_name}  {r.file_path}:{r.line_start}-{r.line_end}  [{', '.join(r.evidence)}]  {r.source_status}")
        for line in r.excerpt.split("\n")[:4]:
            print(f"        {line}")
        for rel in r.relationships[:2]:
            if rel["type"] == "CALL_ORDER":
                print(f"        call order: {rel['first_call']['name']}@{rel['first_call']['line']} {rel['observed_order']} "
                      f"{rel['second_call']['name']}@{rel['second_call']['line']} (syntactic order, not proven runtime order)")
    for warning in response.warnings: print(f"  warning: {warning}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(ROOT / "examples" / "sample_js_repo"))
    args = parser.parse_args()
    print("1) Ingest\n")
    summary = ingest(IngestRequest(source=args.source))
    c = summary.parse_coverage
    print(f"  repository {summary.id} @ {summary.commit_sha}\n  languages {summary.languages}; units {summary.units}; "
          f"parsed {c.files_parsed}/{c.files_seen}, partial {c.files_partial}, failed {c.files_failed}, skipped {c.files_skipped} {c.skipped_reasons}\n")
    for i, question in enumerate(QUESTIONS, 1):
        print(f"2-4) Q{i}: {question!r}")
        for mode in ("hybrid", "adaptive"):
            show(search(SearchRequest(repository_id=summary.id, query=question, mode=mode, top_k=3)))
        trace = search(SearchRequest(repository_id=summary.id, query=question, mode="adaptive", top_k=3)).trace
        print("  adaptive trace: " + " -> ".join(f"{t.action}({t.candidates})" for t in trace) + "\n")
    print("5) Official evaluation (committed artifact)")
    manifest_path = ROOT / "submission" / "mteb_results" / "run_manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        print(f"  {m['task']} {m['split']}: {m['main_score_name']}={m['main_score']} model={m['encoder']['model']} "
              f"device={m['encoder']['device']} elapsed={m['elapsed_seconds']}s\n")
    else:
        print("  not found; run python -m app.evaluation.coir_apps\n")
    print("6) Limitations: static analysis only (syntactic call order, dynamic dispatch unresolved); JavaScript/Python only "
          "(no TypeScript); import bindings not tracked; small general-purpose encoder on CPU.")


if __name__ == "__main__":
    main()
