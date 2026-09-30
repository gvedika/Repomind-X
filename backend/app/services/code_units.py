"""Language-neutral code-unit helpers: stable IDs, span validation and the analyzer interface."""
from __future__ import annotations
import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, Sequence
from app.models.schemas import CodeUnit, FileCoverage, ParseCoverage, ParseStatus

if TYPE_CHECKING:
    from app.services.analyzer import FileAnalysis

EXCLUDED_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "bower_components", "dist", "build", "out",
                 "coverage", "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt", ".cache", ".repomind",
                 "vendor", "target", ".turbo", ".parcel-cache"}
MAX_FILE_BYTES = 512_000


@dataclass(frozen=True)
class AnalysisContext:
    repository_id: str = "unscoped"
    commit_sha: str = "worktree"


class LanguageAnalyzer(Protocol):
    """Every adapter turns one source file into a FileAnalysis carrying canonical CodeUnits."""
    language: str
    extensions: frozenset[str]

    def analyze_file(self, absolute_path: Path, relative_path: str, context: AnalysisContext | None = None) -> "FileAnalysis": ...


def make_unit_id(repository_id: str, commit_sha: str, file_path: str, unit_type: str, qualified_name: str, ordinal: int = 0) -> str:
    """Deterministic for a fixed repo/commit/path/symbol; different commits never share an ID."""
    key = "\x00".join([repository_id, commit_sha, file_path, str(unit_type), qualified_name, str(ordinal)])
    return "cu_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]


def assign_unit_ids(units: list[CodeUnit], context: AnalysisContext) -> list[CodeUnit]:
    """Scope units to a repo/commit; duplicate names in one file get a source-order ordinal."""
    seen: Counter = Counter()
    for unit in sorted(units, key=lambda u: (u.line_start, u.line_end)):
        key = (unit.file_path, unit.unit_type, unit.qualified_name)
        unit.repository_id, unit.commit_sha = context.repository_id, context.commit_sha
        unit.unit_id = make_unit_id(context.repository_id, context.commit_sha, unit.file_path, unit.unit_type, unit.qualified_name, seen[key])
        seen[key] += 1
    return units


_NEWLINE = re.compile(r"\r\n|\r|\n")


def split_lines(text: str) -> list[str]:
    """Split exactly on the line terminators parsers count (unlike str.splitlines, which also splits on \f etc.)."""
    lines = _NEWLINE.split(text)
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def span_is_valid(line_start: int, line_end: int, line_count: int) -> bool:
    return 1 <= line_start <= line_end <= max(line_count, 1)


def excerpt(lines: Sequence[str], line_start: int, line_end: int) -> str:
    """Return one-based inclusive lines; raises ValueError on an out-of-range span."""
    if not span_is_valid(line_start, line_end, len(lines)):
        raise ValueError(f"span {line_start}-{line_end} outside file with {len(lines)} lines")
    return "\n".join(lines[line_start - 1:line_end])


def read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def iter_source_files(root: Path, extensions: set[str], max_bytes: int = MAX_FILE_BYTES):
    """Yield (path, relative, skip_reason) for candidate files, pruning excluded directories."""
    for path in sorted(root.rglob("*")):
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]) or not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        relative = path.relative_to(root).as_posix()
        name = path.name.lower()
        if name.endswith((".min.js", ".bundle.js")) or ".chunk." in name:
            yield path, relative, "generated_bundle"; continue
        try: size = path.stat().st_size
        except OSError: yield path, relative, "unreadable"; continue
        if size > max_bytes:
            yield path, relative, "too_large"; continue
        yield path, relative, None


def analyze_repository(root: Path, analyzers: Sequence[LanguageAnalyzer], context: AnalysisContext | None = None,
                       max_bytes: int = MAX_FILE_BYTES) -> tuple[list["FileAnalysis"], ParseCoverage]:
    """Run every adapter over the repo; parse failures are recorded per file and never abort the repository."""
    from app.services.analyzer import FileAnalysis
    context = context or AnalysisContext()
    by_ext = {ext: analyzer for analyzer in analyzers for ext in analyzer.extensions}
    coverage, analyses = ParseCoverage(), []
    for path, relative, skip in iter_source_files(root, set(by_ext), max_bytes):
        analyzer = by_ext[path.suffix.lower()]
        coverage.files_seen += 1
        if skip:
            coverage.files_skipped += 1
            coverage.skipped_reasons[skip] = coverage.skipped_reasons.get(skip, 0) + 1
            continue
        try:
            analysis = analyzer.analyze_file(path, relative, context)
        except Exception as exc:  # an adapter bug must not cancel the rest of the repository
            analysis = FileAnalysis(path=relative, language=analyzer.language, parse_status=ParseStatus.FAILED, parse_error=f"{type(exc).__name__}: {exc}")
        analyses.append(analysis)
        status = analysis.parse_status
        if status == ParseStatus.OK: coverage.files_parsed += 1
        elif status == ParseStatus.PARTIAL: coverage.files_partial += 1
        else: coverage.files_failed += 1
        if status != ParseStatus.OK:
            coverage.errors.append(FileCoverage(file_path=relative, language=analysis.language, status=status, units=len(analysis.units), reason=(analysis.parse_error or "")[:300]))
        coverage.units += len(analysis.units)
        coverage.by_language[analysis.language] = coverage.by_language.get(analysis.language, 0) + 1
    return analyses, coverage
