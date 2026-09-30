from pathlib import Path
from app.models.schemas import IngestRequest, ParseStatus, SearchRequest, UnitType
from app.retrieval.embedding import HashingEmbedder
from app.retrieval.graph import build_code_graph, resolve_module
from app.services.code_units import AnalysisContext, analyze_repository, excerpt, split_lines
from app.services.js_analyzer import JavaScriptAnalyzer, TypeScriptAnalyzer

SAMPLE = Path(__file__).resolve().parents[2] / "examples" / "sample_ts_repo"


def _analyze():
    analyses, coverage = analyze_repository(SAMPLE, [JavaScriptAnalyzer(), TypeScriptAnalyzer()], AnalysisContext("r", "c"))
    return analyses, coverage, {u.qualified_name: u for a in analyses for u in a.units}


def test_typescript_units_spans_and_coverage():
    analyses, coverage, units = _analyze()
    assert coverage.by_language == {"TypeScript": 4} and coverage.files_parsed == 4 and coverage.files_failed == 0
    assert coverage.skipped_reasons == {"declaration_file": 1} and coverage.ratio == 1.0
    for analysis in analyses:
        lines = split_lines((SAMPLE / analysis.path).read_text(encoding="utf-8"))
        for unit in analysis.units:
            assert unit.language == "TypeScript" and 1 <= unit.line_start <= unit.line_end <= len(lines)
            if unit.unit_type != UnitType.FILE:
                assert unit.source == excerpt(lines, unit.line_start, unit.line_end)
    assert {units[n].unit_type for n in ("LineItem", "Currency", "InvoiceStatus", "Invoice", "InvoiceRepository", "Props")} == {UnitType.TYPE}
    assert units["Notifier"].unit_type == UnitType.CLASS and units["Notifier"].signature == "export abstract class Notifier"
    assert "Notifier.send" not in units                       # abstract signature: no implementation
    assert units["BillingService.remindOverdue"].unit_type == UnitType.METHOD   # TS public_field_definition arrow
    assert units["BillingService.totalDue"].docstring.startswith("Apply tax")
    assert units["Webhooks.verifySignature"].parent == "Webhooks"
    assert units["InvoiceTable"].exports == ["InvoiceTable"] and "formatMoney" in units["InvoiceTable"].calls


def test_overload_signatures_are_not_units():
    _, _, units = _analyze()
    money = [u for u in units.values() if u.qualified_name == "formatMoney"]
    assert len(money) == 1 and (money[0].line_start, money[0].line_end) == (15, 17)


def test_typescript_graph_resolves_imports_and_this_calls():
    analyses, _, _ = _analyze()
    all_units = [u for a in analyses for u in a.units]
    graph = build_code_graph(all_units)
    by_id = {u.unit_id: u for u in all_units}
    calls = {(by_id[e.source].qualified_name, by_id[e.target].qualified_name, e.resolution) for e in graph.edges if e.kind == "CALLS"}
    assert ("BillingService.totalDue", "subtotal", "import_export") in calls
    assert ("BillingService.issue", "BillingService.totalDue", "this_method") in calls
    assert ("InvoiceTable", "formatMoney", "import_export") in calls
    imports = {(by_id[e.source].file_path, by_id[e.target].file_path) for e in graph.edges if e.kind == "IMPORTS"}
    assert ("src/utils/money.ts", "src/models/invoice.ts") in imports   # "../models/invoice.js" -> invoice.ts (ESM TS)
    issue = next(u for u in all_units if u.qualified_name == "BillingService.issue")
    assert {i["name"] for i in graph.unresolved[issue.unit_id]} >= {"this.repo.save", "this.notifier.send"}


def test_resolve_module_variants():
    files = {"src/a.ts", "src/b/index.tsx", "src/c.mts"}
    assert resolve_module("src/x.ts", "./a", files, "TypeScript") == "src/a.ts"
    assert resolve_module("src/x.ts", "./a.js", files, "TypeScript") == "src/a.ts"
    assert resolve_module("src/x.ts", "./b", files, "TypeScript") == "src/b/index.tsx"
    assert resolve_module("src/x.ts", "./c.mjs", files, "TypeScript") == "src/c.mts"
    assert resolve_module("src/x.ts", "react", files, "TypeScript") is None


def test_malformed_typescript_recovers_later_definitions(tmp_path):
    (tmp_path / "bad.ts").write_text("interface A { x: number }\nfunction broken(a: number {\n  return a;\n}\nexport function ok(): number { return 1; }\n", encoding="utf-8")
    analyses, coverage = analyze_repository(tmp_path, [TypeScriptAnalyzer()])
    bad = analyses[0]
    assert bad.parse_status == ParseStatus.PARTIAL and coverage.files_partial == 1
    assert {"A", "ok"} <= {u.name for u in bad.units}


def test_typescript_repo_ingests_and_searches(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.retrieval.service import registry, search
    from app.services import ingestion
    monkeypatch.setattr(settings, "repository_root", tmp_path / "repos")
    monkeypatch.setattr(settings, "graph_backend", "memory")
    monkeypatch.setattr(settings, "chroma_host", None)
    embedder = HashingEmbedder()
    summary = ingestion.ingest(IngestRequest(source=str(SAMPLE)), embedder=embedder)
    assert summary.languages == {"TypeScript": 4} and summary.architecture == "JavaScript front-end application"
    top = search(SearchRequest(repository_id=summary.id, query="apply tax and convert currency for the amount due", top_k=3), embedder).results[0]
    assert top.qualified_name == "BillingService.totalDue" and top.language == "TypeScript" and (top.line_start, top.line_end) == (23, 26)
    kinds = {r.unit_type for r in search(SearchRequest(repository_id=summary.id, query="invoice line item fields", top_k=10), embedder).results}
    assert UnitType.TYPE in kinds
    registry._items.clear()
