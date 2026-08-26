from pathlib import Path
from app.services.analyzer import PythonAnalyzer
from app.services.graph import build_graph
from app.services.graph_backend import InMemoryGraphBackend


def test_python_analysis_and_call_graph(tmp_path: Path):
    source = tmp_path / "service.py"
    source.write_text('''import os\n\ndef validate(value: str) -> bool:\n    return bool(value)\n\ndef login(token):\n    if validate(token):\n        return True\n    return False\n''')
    analysis = PythonAnalyzer().analyze_file(source, "service.py")
    assert [f.name for f in analysis.functions] == ["validate", "login"]
    assert analysis.functions[1].complexity >= 2
    graph = build_graph("test", [analysis], backend=InMemoryGraphBackend())
    assert any(edge.kind == "CALLS" for edge in graph.edges)
