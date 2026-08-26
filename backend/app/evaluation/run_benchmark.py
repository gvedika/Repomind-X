from __future__ import annotations
import argparse,json
from pathlib import Path
from app.evaluation.benchmark import run_all
from app.mlops.tracking import log_experiment


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--repository-id",required=True)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=Path("evaluation_results.json"))
    args=parser.parse_args()
    results=run_all(args.repository_id,args.dataset)
    args.output.write_text(json.dumps(results,indent=2),encoding="utf-8")
    for name,metrics in results.items():
        try: log_experiment(f"repomind-{name}",params={"dataset":str(args.dataset)},metrics=metrics)
        except Exception as exc: print(f"MLflow logging unavailable: {exc}")
    print(json.dumps(results,indent=2))


if __name__=="__main__": main()
