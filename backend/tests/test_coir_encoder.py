import numpy as np
import pytest


class RecordingEmbedder:
    def __init__(self): self.calls = []
    def encode(self, texts, is_query=False):
        self.calls.append((list(texts), is_query))
        return np.ones((len(texts), 4), dtype=np.float32)


def test_encoder_routes_queries_and_documents():
    pytest.importorskip("mteb")
    from mteb.encoder_interface import PromptType
    from app.evaluation.coir_apps import RepoMindEncoder
    encoder = object.__new__(RepoMindEncoder)
    encoder.embedder = RecordingEmbedder()
    out = encoder.encode(["how to sort"], task_name="AppsRetrieval", prompt_type=PromptType.query)
    encoder.encode(("def f(): pass", "x = 1"), task_name="AppsRetrieval", prompt_type=PromptType.document)
    assert out.shape == (1, 4)
    assert encoder.embedder.calls == [(["how to sort"], True), (["def f(): pass", "x = 1"], False)]


def test_official_artifact_is_genuine_mteb_output():
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2] / "submission" / "mteb_results"
    manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))
    result = json.loads((root / manifest["result_file"].replace("\\", "/")).read_text(encoding="utf-8"))
    assert result["task_name"] == "AppsRetrieval" and manifest["split"] == "test"
    assert result["scores"]["test"][0]["main_score"] == manifest["main_score"]
    assert result["dataset_revision"] == manifest["dataset"]["revision"]
