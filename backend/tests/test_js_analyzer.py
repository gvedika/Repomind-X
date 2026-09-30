import json
from pathlib import Path
import pytest
from app.models.schemas import IngestRequest, ParseStatus, UnitType
from app.services.analyzer import PythonAnalyzer
from app.services.code_units import AnalysisContext, analyze_repository, excerpt, split_lines
from app.services.js_analyzer import JavaScriptAnalyzer

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_js_repo"


def _units(path: Path, rel: str):
    analysis = JavaScriptAnalyzer().analyze_file(path, rel, AnalysisContext("r", "c"))
    return analysis, {u.qualified_name: u for u in analysis.units}


def test_sample_repo_units_have_exact_spans():
    analyses, coverage = analyze_repository(SAMPLE, [JavaScriptAnalyzer(), PythonAnalyzer()], AnalysisContext("r", "c"))
    assert coverage.files_parsed == 7 and coverage.files_failed == 0 and coverage.by_language == {"JavaScript": 7}
    for analysis in analyses:
        lines = split_lines((SAMPLE / analysis.path).read_text(encoding="utf-8"))
        for unit in analysis.units:
            assert unit.language == "JavaScript" and 1 <= unit.line_start <= unit.line_end <= len(lines)
            if unit.unit_type != UnitType.FILE:
                assert unit.source == excerpt(lines, unit.line_start, unit.line_end)
    names = {u.qualified_name for a in analyses for u in a.units}
    assert {"hashPassword", "login", "SessionManager", "SessionManager.purgeExpired", "SessionManager.isValid",
            "sessionStore.list", "withRetry", "chunk", "chargeCard", "CartSummary", "router.post('/orders')"} <= names


def test_functions_methods_imports_exports_and_calls():
    analysis, units = _units(SAMPLE / "src/services/auth.js", "src/services/auth.js")
    assert analysis.imports == ["../utils/logger.js", "./userStore.js", "node:crypto"]
    assert analysis.exports == ["SessionManager", "hashPassword", "login"]
    login = units["login"]
    assert (login.line_start, login.line_end) == (23, 37)
    assert login.signature == "export async function login(email, password)"
    assert login.exports == ["login"] and units["safeEqual"].exports == []
    names = [c.name for c in login.call_sites]
    assert names.index("hashPassword") < names.index("safeEqual") < names.index("saveSession")
    assert names.index("crypto.randomBytes") < names.index("*.toString")   # inner call before chained call
    assert all(a.order < b.order for a, b in zip(login.call_sites, login.call_sites[1:]))
    assert units["hashPassword"].docstring.startswith("Derive a salted PBKDF2 digest")
    purge = units["SessionManager.purgeExpired"]
    assert purge.unit_type == UnitType.METHOD and purge.parent == "SessionManager" and "this.store.remove" in purge.calls
    assert units["SessionManager.isValid"].unit_type == UnitType.METHOD   # class field arrow function


def test_commonjs_exports_requires_and_route_handlers():
    retry, units = _units(SAMPLE / "src/utils/retry.cjs", "src/utils/retry.cjs")
    assert retry.imports == ["node:timers/promises"] and retry.exports == ["chunk", "withRetry"]
    assert units["withRetry"].exports == ["withRetry"]
    orders, units = _units(SAMPLE / "src/routes/orders.js", "src/routes/orders.js")
    assert "express" in orders.imports and "../utils/retry.cjs" in orders.imports
    handler = units["router.post('/orders')"]
    assert (handler.line_start, handler.line_end) == (14, 19)
    assert [c.name for c in handler.call_sites][:1] == ["validateOrder"] and "chargeCard" in handler.calls
    assert "anonymous callback named from its call site" in handler.parser_uncertainty


def test_jsx_default_export_and_mjs():
    _, units = _units(SAMPLE / "src/components/CartSummary.jsx", "src/components/CartSummary.jsx")
    assert units["CartSummary"].exports == ["default"] and "formatCurrency" in units["CartSummary"].calls
    payments, units = _units(SAMPLE / "src/services/payments.mjs", "src/services/payments.mjs")
    assert payments.exports == ["chargeCard", "refund"] and "fetch" in units["chargeCard"].calls


def test_nested_prototype_computed_and_anonymous_default(tmp_path):
    path = tmp_path / "a.js"
    path.write_text("function outer(x) {\n  function inner(y) { return helper(y); }\n  return [1].map((n) => inner(n));\n}\n"
                    "Widget.prototype.render = function () { return draw(this); };\n"
                    "class K { [Symbol.iterator]() {} #secret() { return obj[key](); } }\n"
                    "export { outer as main };\nexport default () => 1;\n", encoding="utf-8")
    analysis, units = _units(path, "a.js")
    assert units["outer.inner"].parent == "outer" and units["outer.inner"].calls == ["helper"]
    assert "helper" not in units["outer"].calls and "inner" in units["outer"].calls   # nested unit owns its calls
    assert units["Widget.render"].unit_type == UnitType.METHOD
    assert "computed method name" in units["K.[Symbol.iterator]"].parser_uncertainty
    assert any("dynamic" in note for note in units["K.#secret"].parser_uncertainty)
    assert units["outer"].exports == ["main"] and units["default"].exports == ["default"]
    assert analysis.exports == ["default", "main"]


def test_malformed_file_is_partial_and_recovers_later_definitions(tmp_path):
    (tmp_path / "bad.js").write_text("function ok() { return 1; }\nfunction broken( {\n  return 2;\n}\nfunction after() { return ok(); }\n", encoding="utf-8")
    (tmp_path / "good.js").write_text("export const add = (a, b) => a + b;\n", encoding="utf-8")
    analyses, coverage = analyze_repository(tmp_path, [JavaScriptAnalyzer()])
    assert coverage.files_parsed == 1 and coverage.files_partial == 1 and coverage.ratio == 1.0
    assert coverage.errors[0].file_path == "bad.js" and "line 2" in coverage.errors[0].reason
    bad = next(a for a in analyses if a.path == "bad.js")
    assert bad.parse_status == ParseStatus.PARTIAL
    assert {u.name for u in bad.units if u.unit_type == UnitType.FUNCTION} >= {"ok", "after"}
    good = next(a for a in analyses if a.path == "good.js")
    add = next(u for u in good.units if u.name == "add")
    assert add.source == "export const add = (a, b) => a + b;" and add.exports == ["add"]


def test_exclusions_bundles_binary_and_size_limits(tmp_path):
    for rel, text in {"src/app.js": "function app() {}\n", "node_modules/x/index.js": "function vendored() {}\n",
                      "dist/out.js": "function built() {}\n", "public/vendor.min.js": "function min(){}\n",
                      "src/big.js": "// x\n" * 400}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    (tmp_path / "src/blob.js").write_bytes(b"\x00\x01binary")
    analyses, coverage = analyze_repository(tmp_path, [JavaScriptAnalyzer()], max_bytes=1000)
    assert sorted(a.path for a in analyses) == ["src/app.js", "src/blob.js"]
    assert coverage.skipped_reasons == {"generated_bundle": 1, "too_large": 1}
    assert next(a for a in analyses if a.path == "src/blob.js").parse_status == ParseStatus.SKIPPED


def test_crlf_sources_keep_line_numbers(tmp_path):
    path = tmp_path / "w.js"
    path.write_bytes(b"// header\r\n\r\nfunction f() {\r\n  return g();\r\n}\r\n")
    _, units = _units(path, "w.js")
    assert (units["f"].line_start, units["f"].line_end) == (3, 5) and units["f"].call_sites[0].line == 4


def test_mixed_repo_keeps_python_adapter(tmp_path):
    (tmp_path / "a.js").write_text("function js() {}\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def py():\n    return 1\n", encoding="utf-8")
    analyses, coverage = analyze_repository(tmp_path, [JavaScriptAnalyzer(), PythonAnalyzer()])
    assert coverage.by_language == {"JavaScript": 1, "Python": 1}
    assert {u.name for a in analyses for u in a.units} >= {"js", "py"}


def test_ingest_sample_js_repo_end_to_end(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import ingestion
    stored = []

    class FakeVectors:
        def __init__(self, repository_id): self.repository_id = repository_id
        def upsert(self, documents): stored.extend(documents)

    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", "fake-chroma")
    monkeypatch.setattr(ingestion, "ChromaVectorStore", FakeVectors)
    from app.retrieval.embedding import HashingEmbedder
    summary = ingestion.ingest(IngestRequest(source=str(SAMPLE)), embedder=HashingEmbedder())
    assert summary.languages == {"JavaScript": 7} and summary.architecture == "JavaScript web service / API"
    assert summary.parse_coverage.files_parsed == 7 and summary.units == summary.parse_coverage.units > 20
    assert summary.functions >= 15 and summary.commit_sha
    units_file = next((tmp_path / "repos").glob("*/.repomind/units.jsonl"))
    units = [json.loads(line) for line in units_file.read_text(encoding="utf-8").splitlines()]
    assert len(units) == summary.units and len({u["unit_id"] for u in units}) == len(units)
    assert all(u["repository_id"] == summary.id and u["commit_sha"] == summary.commit_sha for u in units)
    login = next(d for d in stored if d.metadata.get("function") == "login")
    assert login.metadata["language"] == "JavaScript" and login.id == login.metadata["unit_id"] and login.id.startswith("cu_")
    assert "crypto.randomBytes(32)" in login.text and (login.metadata["line_start"], login.metadata["line_end"]) == (23, 37)
