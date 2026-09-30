"""Official Theme 1 screening evaluation: CoIR Apps Retrieval through MTEB, using the RepoMind-X encoder.

Run:  python -m app.evaluation.coir_apps --output ../submission/mteb_results
The MTEB result JSON is written by MTEB itself; this module never edits or synthesizes metric values.
A run manifest (model, hardware, command, split, timing) is written next to it."""
from __future__ import annotations
import torch  # noqa: F401  (Windows: torch must load its DLLs before pyarrow/polars pulled in by mteb)
import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
import numpy as np

TASK = "AppsRetrieval"
SPLIT = "test"


class RepoMindEncoder:
    """MTEB encoder interface over the same embedder/preprocessing used by RepoMind-X semantic retrieval:
    queries get the BGE retrieval instruction, documents (code) are encoded as-is, vectors are L2-normalized."""

    def __init__(self, model_name: str, device: str = "cpu", batch_size: int = 32, max_seq_length: int = 512, query_instruction: str | None = None):
        from app.retrieval.embedding import SentenceTransformerEmbedder
        self.embedder = SentenceTransformerEmbedder(model_name, device=device, batch_size=batch_size, query_instruction=query_instruction)
        self.embedder.model.max_seq_length = max_seq_length
        self.model_name = model_name
        self.mteb_model_meta = _model_meta(model_name, self.embedder)

    def encode(self, sentences, task_name: str | None = None, prompt_type=None, **kwargs) -> np.ndarray:
        is_query = getattr(prompt_type, "value", prompt_type) == "query"
        return self.embedder.encode(list(sentences), is_query=is_query)


def _model_meta(model_name: str, embedder):
    from mteb.model_meta import ModelMeta
    model = embedder.model
    return ModelMeta(name=f"repomind-x/{model_name.split('/')[-1]}", revision="repomind-x-encoder-v1", release_date=None,
                     languages=None, n_parameters=sum(p.numel() for p in model.parameters()), memory_usage_mb=None,
                     max_tokens=model.max_seq_length, embed_dim=model.get_sentence_embedding_dimension(), license=None,
                     open_weights=True, public_training_code=None, public_training_data=None, framework=["Sentence Transformers"],
                     reference=f"https://huggingface.co/{model_name}", similarity_fn_name="cosine", use_instructions=True,
                     training_datasets=None)


def _hardware() -> dict:
    info = {"platform": platform.platform(), "processor": platform.processor(), "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(), "torch": torch.__version__, "torch_threads": torch.get_num_threads(),
            "cuda_used": False}
    try:
        import mteb, sentence_transformers, transformers
        info.update(mteb=mteb.__version__, sentence_transformers=sentence_transformers.__version__, transformers=transformers.__version__)
    except Exception:
        pass
    return info


def run(output: Path, model_name: str, device: str = "cpu", batch_size: int = 32, max_seq_length: int = 512, query_instruction: str | None = None) -> Path:
    import mteb
    if device != "cpu":
        print(f"warning: running on {device}; the documented configuration is CPU", file=sys.stderr)
    output.mkdir(parents=True, exist_ok=True)
    encoder = RepoMindEncoder(model_name, device=device, batch_size=batch_size, max_seq_length=max_seq_length, query_instruction=query_instruction)
    tasks = mteb.get_tasks(tasks=[TASK])
    started_at, started = datetime.now(timezone.utc), perf_counter()
    results = mteb.MTEB(tasks=tasks).run(encoder, output_folder=str(output), eval_splits=[SPLIT], overwrite_results=True,
                                         encode_kwargs={"batch_size": batch_size})
    elapsed = perf_counter() - started
    written = sorted(output.rglob(f"{TASK}.json"))
    if not written: raise RuntimeError("MTEB finished without writing a result file")
    scores = results[0].scores[SPLIT][0] if results else {}
    manifest = {"task": TASK, "split": SPLIT, "dataset": dict(tasks[0].metadata.dataset), "main_score_name": tasks[0].metadata.main_score,
                "main_score": scores.get("main_score"), "ndcg_at_10": scores.get("ndcg_at_10"), "result_file": str(written[-1].relative_to(output)),
                "encoder": {"model": model_name, "device": device, "batch_size": batch_size, "max_seq_length": max_seq_length,
                            "query_instruction": encoder.embedder.query_instruction, "normalize_embeddings": True},
                "command": " ".join([Path(sys.executable).name, "-m", "app.evaluation.coir_apps", *sys.argv[1:]]),
                "started_at_utc": started_at.isoformat(), "elapsed_seconds": round(elapsed, 1), "hardware": _hardware(),
                "note": "Metric values are copied from the MTEB-generated result file of this run; nothing was edited or extrapolated."}
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return written[-1]


def main():
    from app.core.config import settings
    parser = argparse.ArgumentParser(description="Run the CoIR Apps Retrieval (MTEB) evaluation with the RepoMind-X encoder.")
    parser.add_argument("--output", type=Path, default=Path("../submission/mteb_results"))
    parser.add_argument("--model", default=settings.embedding_model)
    parser.add_argument("--device", default=settings.model_device)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-seq-length", type=int, default=512)
    parser.add_argument("--query-instruction", default=None, help="prefix added to queries (default: EMBEDDING_QUERY_INSTRUCTION)")
    args = parser.parse_args()
    path = run(args.output, args.model, args.device, args.batch_size, args.max_seq_length, args.query_instruction)
    print(f"MTEB result written to {path}")
    print((args.output / "run_manifest.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
