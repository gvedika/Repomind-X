"""Resolve an indexed unit back to verified source: repo/commit identity, path containment, span bounds, content match."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from app.models.schemas import CodeUnit, SourceStatus, UnitType
from app.security.input_validation import safe_repository_path
from app.services.code_units import excerpt, split_lines

MAX_EXCERPT_LINES = 60
MAX_EXCERPT_CHARS = 6000


@dataclass
class SourceCheck:
    status: SourceStatus
    excerpt: str = ""
    excerpt_line_end: int = 0
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _bounded(text: str, line_start: int, max_lines: int, max_chars: int) -> tuple[str, int, bool]:
    lines = text.split("\n")
    shown = lines[:max_lines]
    out = "\n".join(shown)
    truncated = len(shown) < len(lines)
    if len(out) > max_chars:
        out = out[:max_chars].rsplit("\n", 1)[0] if "\n" in out[:max_chars] else out[:max_chars]
        truncated = True
    return out, line_start + out.count("\n"), truncated


def verify_source(root: Path, unit: CodeUnit, repository_id: str, commit_sha: str,
                  max_lines: int = MAX_EXCERPT_LINES, max_chars: int = MAX_EXCERPT_CHARS) -> SourceCheck:
    """Never invents a location: invalid or missing sources return no excerpt; stale ones return the indexed snapshot."""
    if unit.repository_id != repository_id or unit.commit_sha != commit_sha:
        return SourceCheck(SourceStatus.INVALID, warnings=["unit belongs to a different repository or commit"])
    relative = PurePosixPath(unit.file_path)
    if relative.is_absolute() or ".." in relative.parts or not unit.file_path:
        return SourceCheck(SourceStatus.INVALID, warnings=["unit path is not repository-relative"])
    try:
        path = safe_repository_path(root, unit.file_path)
    except ValueError:
        return SourceCheck(SourceStatus.INVALID, warnings=["unit path escapes the repository root"])
    if not path.is_file():
        return SourceCheck(SourceStatus.MISSING, warnings=[f"{unit.file_path} is missing from the indexed snapshot"])
    try:
        lines = split_lines(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return SourceCheck(SourceStatus.MISSING, warnings=[f"{unit.file_path} could not be read as UTF-8"])
    try:
        current = excerpt(lines, unit.line_start, unit.line_end)
    except ValueError:
        return SourceCheck(SourceStatus.STALE, warnings=[f"indexed span {unit.line_start}-{unit.line_end} is outside the current file ({len(lines)} lines)"])
    matches = current.startswith(unit.source) if unit.unit_type == UnitType.FILE else current == unit.source
    if not matches:
        text, shown_end, truncated = _bounded(unit.source, unit.line_start, max_lines, max_chars)
        return SourceCheck(SourceStatus.STALE, text, shown_end, truncated,
                           ["file changed since indexing; showing the indexed snapshot, re-ingest to refresh locations"])
    text, shown_end, truncated = _bounded(current, unit.line_start, max_lines, max_chars)
    return SourceCheck(SourceStatus.VERIFIED, text, shown_end, truncated)
