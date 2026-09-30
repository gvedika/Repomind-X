from __future__ import annotations
import argparse, json
from pathlib import Path
from app.evaluation.benchmark import SYSTEMS, run_all
from app.mlops.tracking import log_experiment


def main():
    parser = argparse.ArgumentParser(description="Custom aligned benchmark over canonical code units (not the official MTEB run).")
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--systems", nargs="*", default=list(SYSTEMS))
    parser.add_argument("--output", type=Path, default=Path("evaluation_results.json"))
    args = parser.parse_args()
    results = run_all(args.repository_id, args.dataset, args.systems)
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for name, metrics in results["modes"].items():
        try: log_experiment(f"repomind-{name}", params={"dataset": str(args.dataset)}, metrics={k: v for k, v in metrics.items() if isinstance(v, (int, float))})
        except Exception as exc: print(f"MLflow logging unavailable: {exc}")
    print(json.dumps(results, indent=2))


if __name__ == "__main__": main()
