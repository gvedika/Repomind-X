from pathlib import Path
import pytest
from pydantic import ValidationError
from app.models.schemas import CodeUnit, ParseStatus, UnitType
from app.services.analyzer import PythonAnalyzer
from app.services.code_units import AnalysisContext, analyze_repository, excerpt, make_unit_id, split_lines

SOURCE = '''"""Auth helpers."""
import os
from hashlib import sha256

__all__ = ["login", "Session"]


def _hash(value):
    return sha256(value.encode()).hexdigest()


@audit("login")
def login(user, password):
    """Check a password against the stored hash."""
    if _hash(password) == os.environ["HASH"]:
        return Session(user)
    return None


class Session:
    """A logged-in session."""

    def __init__(self, user):
        self.user = user

    async def refresh(self, token):
        return self.validate(token)
'''


def _write(tmp_path: Path, name="auth.py", text=SOURCE) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_python_emits_canonical_units_with_valid_spans(tmp_path):
    path = _write(tmp_path)
    analysis = PythonAnalyzer().analyze_file(path, "auth.py", AnalysisContext("repo1", "abc123"))
    assert analysis.parse_status == ParseStatus.OK
    by_name = {u.qualified_name: u for u in analysis.units}
    assert set(by_name) == {"auth.py", "_hash", "login", "Session", "Session.__init__", "Session.refresh"}
    assert by_name["auth.py"].unit_type == UnitType.FILE
    assert by_name["Session.refresh"].unit_type == UnitType.METHOD and by_name["Session.refresh"].parent == "Session"
    assert by_name["login"].signature == "def login(user, password)"
    assert by_name["Session.refresh"].signature.startswith("async def refresh(")
    assert by_name["login"].docstring == "Check a password against the stored hash."
    assert by_name["login"].exports == ["login"] and by_name["_hash"].exports == []
    assert [s.name for s in by_name["login"].call_sites] == ["audit", "_hash", "Session"]
    lines = split_lines(path.read_text(encoding="utf-8"))
    for unit in analysis.units:
        assert unit.repository_id == "repo1" and unit.commit_sha == "abc123" and unit.language == "Python"
        assert 1 <= unit.line_start <= unit.line_end <= len(lines)
        if unit.unit_type != UnitType.FILE:
            assert unit.source == excerpt(lines, unit.line_start, unit.line_end)
    # Decorators are part of the definition span; the body is the real implementation.
    assert by_name["login"].source.startswith('@audit("login")') and "os.environ" in by_name["login"].source
    assert lines[by_name["login"].line_start - 1] == '@audit("login")'


def test_call_sites_keep_source_order(tmp_path):
    path = _write(tmp_path, text="def f():\n    b()\n    a()\n    b()\n    (lambda: 1)()\n")
    unit = next(u for u in PythonAnalyzer().analyze_file(path, "m.py").units if u.name == "f")
    assert [(s.name, s.line, s.order) for s in unit.call_sites] == [("b", 2, 0), ("a", 3, 1), ("b", 4, 2)]
    assert unit.calls == ["a", "b"]
    assert unit.parser_uncertainty  # the lambda call cannot be named statically


def test_unit_ids_are_deterministic_and_commit_scoped(tmp_path):
    path = _write(tmp_path)
    ids = lambda ctx: [u.unit_id for u in PythonAnalyzer().analyze_file(path, "auth.py", ctx).units]
    first, again = ids(AnalysisContext("repo1", "c1")), ids(AnalysisContext("repo1", "c1"))
    assert first == again and len(set(first)) == len(first)
    assert set(first).isdisjoint(ids(AnalysisContext("repo1", "c2")))
    assert set(first).isdisjoint(ids(AnalysisContext("repo2", "c1")))
    assert make_unit_id("r", "c", "a.py", "function", "f") == make_unit_id("r", "c", "a.py", "function", "f")


def test_duplicate_symbols_in_one_file_get_distinct_ids(tmp_path):
    path = _write(tmp_path, text="def f():\n    return 1\n\ndef f():\n    return 2\n")
    units = [u for u in PythonAnalyzer().analyze_file(path, "d.py").units if u.name == "f"]
    assert len(units) == 2 and units[0].unit_id != units[1].unit_id


def test_parse_failure_is_recorded_per_file_not_fatal(tmp_path):
    _write(tmp_path, "good.py", "def ok():\n    return 1\n")
    _write(tmp_path, "bad.py", "def broken(:\n    pass\n")
    _write(tmp_path, "node_modules/lib.py", "def vendored():\n    pass\n")
    analyses, coverage = analyze_repository(tmp_path, [PythonAnalyzer()], AnalysisContext("r", "c"))
    assert sorted(a.path for a in analyses) == ["bad.py", "good.py"]
    assert coverage.files_parsed == 1 and coverage.files_failed == 1
    assert coverage.errors[0].file_path == "bad.py" and coverage.errors[0].status == ParseStatus.FAILED
    assert coverage.ratio == 0.5 and coverage.by_language == {"Python": 2}
    bad = next(a for a in analyses if a.path == "bad.py")
    assert bad.units == [] and bad.parse_error


def test_large_files_are_skipped_with_reason(tmp_path):
    _write(tmp_path, "big.py", "x = 1\n" * 2000)
    analyses, coverage = analyze_repository(tmp_path, [PythonAnalyzer()], max_bytes=100)
    assert analyses == [] and coverage.files_skipped == 1 and coverage.skipped_reasons == {"too_large": 1}


def test_schema_rejects_zero_based_lines_and_bad_types():
    base = dict(unit_id="cu_x", repository_id="r", commit_sha="c", language="JavaScript", unit_type="function",
                name="f", qualified_name="f", file_path="a.js", line_start=1, line_end=2)
    assert CodeUnit(**base).unit_type == UnitType.FUNCTION
    with pytest.raises(ValidationError): CodeUnit(**{**base, "line_start": 0})
    with pytest.raises(ValidationError): CodeUnit(**{**base, "unit_type": "lambda"})


def test_excerpt_rejects_out_of_range_spans():
    lines = split_lines("a\r\nb\rc\nd\x0ce\n")  # form feed is not a line break for parsers
    assert lines == ["a", "b", "c", "d\x0ce"]
    assert excerpt(lines, 2, 3) == "b\nc"
    with pytest.raises(ValueError): excerpt(lines, 3, 9)
    with pytest.raises(ValueError): excerpt(lines, 0, 1)
