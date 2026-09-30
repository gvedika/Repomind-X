"""Turn canonical code units into retrieval documents that contain the implementation, not only metadata."""
from __future__ import annotations
from app.models.schemas import CodeUnit, UnitType

RETRIEVABLE_TYPES = {UnitType.FUNCTION, UnitType.METHOD, UnitType.CLASS}
BODY_CHARS = 2400


def retrieval_units(units: list[CodeUnit]) -> list[CodeUnit]:
    """Functions, methods and classes; a file unit is kept only when its file has no finer-grained unit."""
    files_with_units = {u.file_path for u in units if u.unit_type in RETRIEVABLE_TYPES}
    return [u for u in units if u.unit_type in RETRIEVABLE_TYPES or
            (u.unit_type == UnitType.FILE and u.file_path not in files_with_units and u.source.strip())]


def document_text(unit: CodeUnit, body_chars: int = BODY_CHARS) -> str:
    """Symbol identity + signature + docstring + source body (bounded for embedding context windows)."""
    header = [f"{unit.language} {unit.unit_type.value} {unit.qualified_name}", f"file: {unit.file_path}"]
    if unit.signature: header.append(unit.signature)
    if unit.docstring: header.append(unit.docstring)
    body = unit.source if len(unit.source) <= body_chars else unit.source[:body_chars]
    return "\n".join([*header, body])
