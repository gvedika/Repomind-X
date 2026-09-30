"""Conservative static code graph over canonical units: CONTAINS, DEFINES, EXPORTS, IMPORTS, CALLS.

A CALLS edge is created only when the callee is resolvable from parser facts (same file scope, `this.` inside a
class, an export of an imported repository module, or an exact qualified-name match). Everything else — dynamic
dispatch, computed members, external libraries, ambiguous names — stays in `unresolved` and is never guessed."""
from __future__ import annotations
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from app.models.schemas import CodeUnit, UnitType

JS_SUFFIXES = ("", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts", "/index.js", "/index.mjs", "/index.jsx", "/index.ts", "/index.tsx")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    resolution: str = ""
    line: int | None = None

    def as_dict(self, units: dict[str, CodeUnit] | None = None) -> dict:
        out = {"type": self.kind, "from": self.source, "to": self.target, "resolution": self.resolution}
        if self.line is not None: out["line"] = self.line
        if units:
            for key, uid in (("from_name", self.source), ("to_name", self.target)):
                if uid in units: out[key] = f"{units[uid].file_path}::{units[uid].qualified_name}"
        return out


@dataclass
class CodeGraph:
    units: dict[str, CodeUnit]
    edges: list[Edge] = field(default_factory=list)
    unresolved: dict[str, list[dict]] = field(default_factory=dict)
    external_imports: dict[str, list[str]] = field(default_factory=dict)

    def __post_init__(self):
        self.out_edges: dict[str, list[Edge]] = defaultdict(list)
        self.in_edges: dict[str, list[Edge]] = defaultdict(list)

    def add(self, edge: Edge) -> None:
        if edge.source == edge.target and edge.kind != "CALLS": return
        self.edges.append(edge)
        self.out_edges[edge.source].append(edge)
        self.in_edges[edge.target].append(edge)

    def callers(self, unit_id: str) -> list[Edge]: return [e for e in self.in_edges.get(unit_id, []) if e.kind == "CALLS"]
    def callees(self, unit_id: str) -> list[Edge]: return [e for e in self.out_edges.get(unit_id, []) if e.kind == "CALLS"]

    def expand(self, seeds: list[str], max_hops: int = 1, fanout: int = 8, kinds: set[str] | None = None, limit: int = 40) -> list[tuple[str, Edge, int]]:
        """Breadth-first neighbours of seeds (both directions) with hop, fan-out and total limits."""
        kinds = kinds or {"CALLS"}
        seen, frontier, found = set(seeds), list(seeds), []
        for hop in range(1, max_hops + 1):
            nxt = []
            for node in frontier:
                neighbours = [(e.target, e) for e in self.out_edges.get(node, []) if e.kind in kinds] + \
                             [(e.source, e) for e in self.in_edges.get(node, []) if e.kind in kinds]
                for other, edge in neighbours[:fanout]:
                    if other in seen or other not in self.units: continue
                    seen.add(other); nxt.append(other); found.append((other, edge, hop))
                    if len(found) >= limit: return found
            frontier = nxt
        return found


def _file_id(unit_by_path: dict[str, CodeUnit], path: str) -> str | None:
    unit = unit_by_path.get(path)
    return unit.unit_id if unit else None


def resolve_module(importer: str, spec: str, files: set[str], language: str) -> str | None:
    """Map an import specifier to an indexed repository file, or None for external/unknown modules."""
    if language in {"JavaScript", "TypeScript"}:
        if not spec.startswith("."): return None
        base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
        found = next((base + s for s in JS_SUFFIXES if base + s in files), None)
        if found is None and language == "TypeScript":   # ESM TypeScript imports "./x.js" for the source file x.ts
            stem = base.rsplit(".", 1)[0] if base.endswith((".js", ".jsx", ".mjs", ".cjs")) else None
            found = next((stem + s for s in (".ts", ".tsx", ".mts", ".cts") if stem and stem + s in files), None)
        return found
    if language == "Python":
        if spec in {".", ""}: return None
        candidate = spec.replace(".", "/")
        return next((c for c in (f"{candidate}.py", f"{candidate}/__init__.py") if c in files), None) or \
            next((f for f in files if f.endswith(f"/{candidate}.py")), None)
    return None


def build_code_graph(units: list[CodeUnit]) -> CodeGraph:
    by_id = {u.unit_id: u for u in units}
    graph = CodeGraph(by_id)
    files = {u.file_path: u for u in units if u.unit_type == UnitType.FILE}
    in_file: dict[str, list[CodeUnit]] = defaultdict(list)
    for u in units:
        if u.unit_type != UnitType.FILE: in_file[u.file_path].append(u)
    by_qualified: dict[str, list[CodeUnit]] = defaultdict(list)
    for u in units:
        if u.unit_type != UnitType.FILE: by_qualified[u.qualified_name].append(u)

    exports: dict[str, dict[str, CodeUnit]] = defaultdict(dict)
    for path, members in in_file.items():
        file_unit = files.get(path)
        for u in members:
            parent = next((m for m in members if m.qualified_name == u.parent), None) if u.parent else None
            container = parent or file_unit
            if container is not None:
                graph.add(Edge(container.unit_id, u.unit_id, "CONTAINS" if parent else "DEFINES", "syntax"))
            for name in u.exports:
                exports[path][name] = u
                exports[path].setdefault(u.name, u)
                if file_unit is not None: graph.add(Edge(file_unit.unit_id, u.unit_id, "EXPORTS", "syntax"))

    imported_files: dict[str, list[str]] = {}
    for path, file_unit in files.items():
        targets = []
        for spec in file_unit.imports:
            target = resolve_module(path, spec, set(files), file_unit.language)
            if target:
                targets.append(target)
                graph.add(Edge(file_unit.unit_id, files[target].unit_id, "IMPORTS", "module_path"))
            else:
                graph.external_imports.setdefault(path, []).append(spec)
        imported_files[path] = targets

    for u in units:
        if u.unit_type == UnitType.FILE or not u.call_sites: continue
        local = {m.name: m for m in in_file[u.file_path] if m.parent is None}
        scope = {m.name: m for m in in_file[u.file_path] if u.parent and m.parent == u.parent}
        nested = {m.name: m for m in in_file[u.file_path] if m.parent == u.qualified_name}
        owner_class = u.parent if u.unit_type == UnitType.METHOD else None
        unresolved = []
        for site in u.call_sites:
            target, how = None, ""
            name = site.name
            if "." not in name and not name.startswith("*"):
                if name in nested: target, how = nested[name], "nested_scope"
                elif name in scope: target, how = scope[name], "enclosing_scope"
                elif name in local and local[name].unit_id != u.unit_id: target, how = local[name], "same_file"
                elif name in local: target, how = local[name], "recursion"
                else:
                    matches = [exports[f][name] for f in imported_files.get(u.file_path, []) if name in exports.get(f, {})]
                    if len(matches) == 1: target, how = matches[0], "import_export"
            elif name.startswith("this.") and owner_class and name.count(".") == 1:
                candidates = by_qualified.get(f"{owner_class}.{name[5:]}", [])
                same = [c for c in candidates if c.file_path == u.file_path]
                if len(same) == 1: target, how = same[0], "this_method"
            elif not name.startswith("*"):
                candidates = [c for c in by_qualified.get(name, []) if c.file_path == u.file_path or c.file_path in imported_files.get(u.file_path, [])]
                if len(candidates) == 1: target, how = candidates[0], "qualified_name"
            if target is not None:
                graph.add(Edge(u.unit_id, target.unit_id, "CALLS", how, site.line))
            else:
                reason = "dynamic receiver" if name.startswith("*") or re.match(r"^[a-z_$][\w$]*\.", name) else "external or unknown symbol"
                unresolved.append({"name": name, "line": site.line, "reason": reason})
        if unresolved: graph.unresolved[u.unit_id] = unresolved
    return graph


def ordered_call_evidence(units: list[CodeUnit], first: str, second: str) -> list[dict]:
    """Units whose source contains calls matching both names, with observed syntactic order.
    Syntactic order is not runtime order: branches, loops, callbacks and async code can reorder execution."""
    def matches(site_name: str, wanted: str) -> bool:
        wanted = wanted.strip("`'\"() ").lower()
        return site_name.lower() == wanted or site_name.lower().rsplit(".", 1)[-1] == wanted.rsplit(".", 1)[-1]

    out = []
    for u in units:
        a = [s for s in u.call_sites if matches(s.name, first)]
        b = [s for s in u.call_sites if matches(s.name, second)]
        if not a or not b: continue
        before = a[0].order < b[0].order
        out.append({"unit_id": u.unit_id, "qualified_name": u.qualified_name, "file_path": u.file_path,
                    "first_call": {"name": a[0].name, "line": a[0].line}, "second_call": {"name": b[0].name, "line": b[0].line},
                    "observed_order": "before" if before else "after",
                    "caveat": "syntactic source order inside one unit; static analysis cannot prove runtime order across branches, loops, callbacks or async boundaries"})
    return out
