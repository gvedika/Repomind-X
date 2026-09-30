"""Tree-sitter JavaScript (.js/.jsx/.mjs/.cjs) and TypeScript (.ts/.tsx/.mts/.cts) adapters behind the canonical
LanguageAnalyzer interface. TypeScript reuses the JavaScript walker plus TS-only declarations (interfaces, type
aliases, enums, namespaces, abstract classes); signature-only declarations (overloads, abstract methods) have no
implementation and are not emitted as units.

Only syntactic facts are extracted. Call-site order is source order inside a unit, which is not proof of
runtime execution order; calls through computed/dynamic expressions are reported as parser uncertainty."""
from __future__ import annotations
import re
from functools import lru_cache
from pathlib import Path
from app.models.schemas import CallSite, CodeUnit, FunctionFact, ParseStatus, UnitType
from app.services.analyzer import FileAnalysis
from app.services.code_units import AnalysisContext, assign_unit_ids, excerpt, split_lines

FUNCTION_NODES = {"function_declaration", "generator_function_declaration", "function_expression", "function",
                  "generator_function", "arrow_function", "method_definition"}
FUNCTION_VALUES = FUNCTION_NODES - {"function_declaration", "generator_function_declaration", "method_definition"}
CLASS_NODES = {"class_declaration", "class", "abstract_class_declaration"}
TYPE_NODES = {"interface_declaration", "type_alias_declaration", "enum_declaration"}
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "all", "use", "route", "options", "head"}
FILE_SOURCE_LIMIT = 20_000
SIGNATURE_LIMIT = 300


@lru_cache(maxsize=3)
def _parser(dialect: str = "javascript"):
    from tree_sitter import Language, Parser
    if dialect == "javascript":
        import tree_sitter_javascript
        return Parser(Language(tree_sitter_javascript.language()))
    import tree_sitter_typescript
    grammar = tree_sitter_typescript.language_tsx() if dialect == "tsx" else tree_sitter_typescript.language_typescript()
    return Parser(Language(grammar))


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _field(node, name):
    return node.child_by_field_name(name) if node is not None else None


def _dotted(node) -> str | None:
    """identifier / this / a.b.c chains; None for computed or call-result objects."""
    if node is None: return None
    if node.type in {"identifier", "property_identifier", "private_property_identifier", "shorthand_property_identifier"}: return _text(node)
    if node.type in {"this", "super"}: return node.type
    if node.type == "member_expression":
        obj, prop = _dotted(_field(node, "object")), _field(node, "property")
        return f"{obj}.{_text(prop)}" if obj and prop is not None else None
    return None


def _string_value(node) -> str | None:
    if node is not None and node.type == "string":
        return "".join(_text(c) for c in node.named_children if c.type == "string_fragment")
    if node is not None and node.type == "template_string" and not any(c.type == "template_substitution" for c in node.named_children):
        return _text(node)[1:-1]
    return None


def _jsdoc(node) -> str | None:
    """A /** ... */ block that ends on the line directly above the definition."""
    prev = node.prev_sibling
    if prev is None or prev.type != "comment": return None
    raw = _text(prev)
    if not raw.startswith("/**") or node.start_point[0] - prev.end_point[0] > 1: return None
    body = [re.sub(r"^\s*\*\s?", "", line) for line in raw[3:-2].split("\n")]
    return "\n".join(body).strip() or None


class _FileWalker:
    def __init__(self, relative_path: str, lines: list[str], language: str = "JavaScript"):
        self.path, self.lines, self.language = relative_path, lines, language
        self.units: list[CodeUnit] = []
        self.imports: list[str] = []
        self.exports: set[str] = set()
        self.local_exports: dict[str, str] = {}   # local name -> exported name
        self.unit_nodes: set[int] = set()

    # -- unit construction -------------------------------------------------------------------------------
    def add_unit(self, span_node, fn_node, name, qualified, unit_type, parent=None, doc_node=None, uncertainty=None, exported=None):
        start, end = span_node.start_point[0] + 1, span_node.end_point[0] + 1
        if span_node.end_point[1] == 0 and end > start: end -= 1   # node ending at column 0 belongs to previous line
        end = min(end, len(self.lines))
        body = _field(fn_node, "body")
        header_end = body.start_byte if body is not None else fn_node.end_byte
        signature = " ".join(span_node.text[: max(header_end - span_node.start_byte, 0)].decode("utf-8", "replace").split())
        signature = signature.rstrip("{").rstrip().removesuffix("=>").rstrip()[:SIGNATURE_LIMIT] or None
        notes = list(uncertainty or [])
        if fn_node.has_error: notes.append("syntax errors inside unit")
        unit = CodeUnit(unit_id="", repository_id="", commit_sha="", language=self.language, unit_type=unit_type, name=name,
                        qualified_name=qualified, signature=signature, file_path=self.path, line_start=start, line_end=end,
                        source=excerpt(self.lines, start, end), docstring=_jsdoc(doc_node or span_node), imports=[],
                        parent=parent, exports=[exported] if exported else [], parser_uncertainty=notes)
        self.units.append(unit)
        self.unit_nodes.add(fn_node.id)
        return unit, fn_node

    # -- traversal ---------------------------------------------------------------------------------------
    def walk(self, node, scope: str | None = None, pending: list | None = None):
        """Collect units depth-first; `pending` receives (unit, fn_node) pairs for call extraction."""
        pending = pending if pending is not None else []
        t = node.type
        if t == "import_statement":
            source = _string_value(_field(node, "source"))
            if source: self.imports.append(source)
            return pending
        if t == "export_statement":
            self._exports(node, pending)
        if t in {"function_declaration", "generator_function_declaration"}:
            name = _text(_field(node, "name"))
            span = node.parent if node.parent is not None and node.parent.type == "export_statement" else node
            pending.append(self._named_function(span, node, name, scope, exported=self._export_name(span, name)))
            self.walk(_field(node, "body"), self._q(scope, name), pending)
            return pending
        if t in TYPE_NODES and _field(node, "name") is not None:
            name = _text(_field(node, "name"))
            span = node.parent if node.parent is not None and node.parent.type == "export_statement" else node
            pending.append(self.add_unit(span, node, name, self._q(scope, name), UnitType.TYPE, parent=scope, exported=self._export_name(span, name)))
            return pending
        if t == "internal_module" and _field(node, "name") is not None:   # TypeScript namespace
            self.walk(_field(node, "body"), self._q(scope, _text(_field(node, "name"))), pending)
            return pending
        if t in CLASS_NODES and _field(node, "name") is not None:
            self._class(node, _text(_field(node, "name")), node.parent if node.parent is not None and node.parent.type == "export_statement" else node, scope, pending)
            return pending
        if t == "variable_declarator":
            name_node, value = _field(node, "name"), _field(node, "value")
            if name_node is not None and name_node.type == "identifier" and value is not None:
                name = _text(name_node)
                statement = node.parent if node.parent is not None else node
                span = statement.parent if statement.parent is not None and statement.parent.type == "export_statement" else statement
                if len(statement.named_children) > 1: span = node   # `const a = () => 1, b = () => 2`
                if value.type in FUNCTION_VALUES:
                    pending.append(self._named_function(span, value, name, scope, doc_node=span, exported=self._export_name(span, name)))
                    self.walk(_field(value, "body"), self._q(scope, name), pending)
                    return pending
                if value.type == "class":
                    self._class(value, name, span, scope, pending, doc_node=span); return pending
                if value.type == "object":
                    self._object_members(value, self._q(scope, name), pending)
                    return pending
                if value.type == "call_expression": self._require(value)
        if t == "assignment_expression":
            if self._assignment(node, scope, pending): return pending
        if t == "call_expression":
            self._require(node)
            if self._route_callback(node, scope, pending): return pending
        for child in node.named_children:
            self.walk(child, scope, pending)
        return pending

    @staticmethod
    def _q(scope, name):
        return f"{scope}.{name}" if scope else name

    def _named_function(self, span, fn_node, name, scope, doc_node=None, exported=None, unit_type=UnitType.FUNCTION, uncertainty=None):
        return self.add_unit(span, fn_node, name, self._q(scope, name), unit_type, parent=scope, doc_node=doc_node, exported=exported, uncertainty=uncertainty)

    def _class(self, class_node, name, span, scope, pending, doc_node=None):
        qualified = self._q(scope, name)
        pending.append(self.add_unit(span, class_node, name, qualified, UnitType.CLASS, parent=scope, doc_node=doc_node, exported=self._export_name(span, name)))
        body = _field(class_node, "body")
        for member in body.named_children if body is not None else []:
            if member.type == "method_definition":
                key = _field(member, "name")
                method = _text(key)
                note = ["computed method name"] if key is not None and key.type == "computed_property_name" else None
                pending.append(self._named_function(member, member, method, qualified, unit_type=UnitType.METHOD, uncertainty=note))
                self.walk(_field(member, "body"), self._q(qualified, method), pending)
            elif member.type in {"field_definition", "public_field_definition"}:
                prop, value = _field(member, "property") or _field(member, "name"), _field(member, "value")
                if prop is not None and value is not None and value.type in FUNCTION_VALUES:
                    pending.append(self._named_function(member, value, _text(prop), qualified, doc_node=member, unit_type=UnitType.METHOD))
                    self.walk(_field(value, "body"), self._q(qualified, _text(prop)), pending)

    def _object_members(self, obj, owner, pending):
        for member in obj.named_children:
            if member.type == "method_definition":
                name = _text(_field(member, "name"))
                pending.append(self._named_function(member, member, name, owner, unit_type=UnitType.METHOD))
                self.walk(_field(member, "body"), self._q(owner, name), pending)
            elif member.type == "pair":
                key, value = _field(member, "key"), _field(member, "value")
                if key is not None and key.type in {"property_identifier", "string"} and value is not None and value.type in FUNCTION_VALUES:
                    name = _string_value(key) if key.type == "string" else _text(key)
                    pending.append(self._named_function(member, value, name, owner, doc_node=member, unit_type=UnitType.METHOD))
                    self.walk(_field(value, "body"), self._q(owner, name), pending)
                elif value is not None:
                    self.walk(value, owner, pending)
            else:
                self.walk(member, owner, pending)

    def _assignment(self, node, scope, pending) -> bool:
        left, right = _field(node, "left"), _field(node, "right")
        target = _dotted(left)
        if not target or right is None: return False
        statement = node.parent if node.parent is not None and node.parent.type == "expression_statement" else node
        exported = None
        if target in {"module.exports", "exports"}:
            if right.type == "object":
                for member in right.named_children:
                    key = _field(member, "key") if member.type == "pair" else member if member.type == "shorthand_property_identifier" else None
                    if key is not None:
                        exported_name = _text(key)
                        self.exports.add(exported_name)
                        value = _field(member, "value") if member.type == "pair" else None
                        if value is not None and value.type == "identifier": self.local_exports[_text(value)] = exported_name
                        elif value is None: self.local_exports[exported_name] = exported_name
                self._object_members(right, None, pending)
                return True
            if right.type == "identifier":
                self.exports.add("default"); self.local_exports[_text(right)] = "default"; return True
            exported, name = "default", "module.exports"
        elif target.startswith(("module.exports.", "exports.")):
            name = target.split(".")[-1]; exported = name; self.exports.add(name)
            if right.type == "identifier": self.local_exports[_text(right)] = name; return True
        else:
            name = target
        if right.type in FUNCTION_VALUES:
            unit_type = UnitType.METHOD if ".prototype." in target else UnitType.FUNCTION
            owner = target.split(".prototype.")[0] if unit_type == UnitType.METHOD else scope
            short = target.split(".")[-1] if unit_type == UnitType.METHOD else name
            pending.append(self.add_unit(statement, right, short, self._q(owner, short) if unit_type == UnitType.METHOD else self._q(scope, name),
                                         unit_type, parent=owner, doc_node=statement, exported=exported))
            self.walk(_field(right, "body"), self._q(scope, name), pending)
            return True
        if right.type == "class":
            self._class(right, name, statement, scope, pending, doc_node=statement); return True
        return False

    def _route_callback(self, call, scope, pending) -> bool:
        """Name inline handlers like app.get('/users', (req, res) => ...) after their call site."""
        callee = _dotted(_field(call, "function"))
        args = _field(call, "arguments")
        if not callee or "." not in callee or args is None or callee.split(".")[-1] not in ROUTE_METHODS: return False
        values = args.named_children
        route = _string_value(values[0]) if values else None
        handlers = [v for v in values[1:] if v.type in FUNCTION_VALUES]
        if route is None or not handlers: return False
        statement = call.parent if call.parent is not None and call.parent.type == "expression_statement" else call
        for index, handler in enumerate(handlers):
            name = f"{callee}({route!r})" + (f"#{index}" if len(handlers) > 1 else "")
            span = statement if len(handlers) == 1 else handler
            pending.append(self.add_unit(span, handler, name, self._q(scope, name), UnitType.FUNCTION, parent=scope, doc_node=statement,
                                         uncertainty=["anonymous callback named from its call site"]))
            self.walk(_field(handler, "body"), self._q(scope, name), pending)
        return True

    def _require(self, call):
        if _text(_field(call, "function")) == "require":
            args = _field(call, "arguments")
            value = _string_value(args.named_children[0]) if args is not None and args.named_children else None
            if value: self.imports.append(value)

    def _export_name(self, span, name) -> str | None:
        if span.type != "export_statement": return None
        exported = "default" if any(c.type == "default" for c in span.children) else name
        self.exports.add(exported)
        return exported

    def _exports(self, node, pending):
        source = _string_value(_field(node, "source"))
        if source: self.imports.append(source)
        for clause in (c for c in node.named_children if c.type == "export_clause"):
            for spec in clause.named_children:
                local, alias = _field(spec, "name"), _field(spec, "alias")
                exported = _text(alias or local)
                self.exports.add(exported)
                if not source: self.local_exports[_text(local)] = exported
        declaration = _field(node, "declaration")
        if declaration is not None and declaration.type in {"lexical_declaration", "variable_declaration"}:
            for declarator in declaration.named_children:
                name = _field(declarator, "name")
                if name is not None and name.type == "identifier": self.exports.add(_text(name))
        value = _field(node, "value")
        if value is not None and any(c.type == "default" for c in node.children) and value.type == "identifier":
            self.exports.add("default"); self.local_exports[_text(value)] = "default"
        elif value is not None and value.type in FUNCTION_VALUES | {"class"} and _field(value, "name") is None:
            self.exports.add("default")
            pending.append(self.add_unit(node, value, "default", "default", UnitType.CLASS if value.type == "class" else UnitType.FUNCTION, exported="default"))

    # -- calls -------------------------------------------------------------------------------------------
    def calls(self, fn_node) -> tuple[list[CallSite], int]:
        sites, unresolved, stack = [], 0, [(c, 0) for c in reversed(fn_node.named_children)]
        while stack:
            node, depth = stack.pop()
            if node.id in self.unit_nodes: continue          # nested named units own their own calls
            if node.type in {"call_expression", "new_expression"}:
                target = _field(node, "function") if node.type == "call_expression" else _field(node, "constructor")
                name = _dotted(target)
                if name is None and target is not None and target.type == "member_expression":
                    prop = _field(target, "property")
                    name = f"*.{_text(prop)}" if prop is not None and prop.type == "property_identifier" else None
                    unresolved += 1
                elif name is None: unresolved += 1
                if name: sites.append((node.start_point, -depth, name, node.start_point[0] + 1))
            stack.extend((c, depth + 1) for c in reversed(node.named_children))
        sites.sort()   # source position; for chained a().b() the inner (deeper) call comes first
        return [CallSite(name=n, line=line, order=i) for i, (_, _, n, line) in enumerate(sites)], unresolved


class JavaScriptAnalyzer:
    language = "JavaScript"
    extensions = frozenset({".js", ".jsx", ".mjs", ".cjs"})

    def dialect(self, relative_path: str) -> str:
        return "javascript"

    def analyze_file(self, absolute_path: Path, relative_path: str, context: AnalysisContext | None = None) -> FileAnalysis:
        context = context or AnalysisContext()
        result = FileAnalysis(path=relative_path, language=self.language)
        try:
            raw = absolute_path.read_bytes()
            text = raw.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            result.parse_status, result.parse_error = ParseStatus.FAILED, f"{type(exc).__name__}: {exc}"; return result
        if b"\x00" in raw:
            result.parse_status, result.parse_error = ParseStatus.SKIPPED, "binary content"; return result
        text = text.replace("\r\n", "\n").replace("\r", "\n")   # tree-sitter rows count only \n
        lines = split_lines(text)
        parser = _parser(self.dialect(relative_path))
        tree = parser.parse(text.encode("utf-8"))
        walker = _FileWalker(relative_path, lines, self.language)
        pending = walker.walk(tree.root_node) if not tree.root_node.has_error else _recover(text, walker, parser)
        walker.imports = sorted(set(walker.imports))
        for unit, fn_node in pending:
            sites, unresolved = walker.calls(fn_node)
            unit.call_sites, unit.calls, unit.imports = sites, sorted({s.name for s in sites}), walker.imports
            if unresolved: unit.parser_uncertainty.append(f"{unresolved} call(s) on dynamic expressions not fully resolved")
            exported = walker.local_exports.get(unit.name) if unit.parent is None else None
            if exported and exported not in unit.exports: unit.exports.append(exported)
        for unit in walker.units:
            if unit.unit_type in {UnitType.FUNCTION, UnitType.METHOD}:
                result.functions.append(FunctionFact(qualified_name=unit.qualified_name, name=unit.name, file_path=relative_path,
                    line_start=unit.line_start, line_end=unit.line_end, docstring=unit.docstring, calls=unit.calls))
            elif unit.unit_type == UnitType.CLASS:
                methods = [u.qualified_name for u in walker.units if u.parent == unit.qualified_name and u.unit_type == UnitType.METHOD]
                result.classes.append({"name": unit.qualified_name, "bases": [], "line": unit.line_start, "methods": methods})
        result.imports, result.exports = walker.imports, sorted(walker.exports)
        uncertainty = ["file source truncated for storage"] if len(text) > FILE_SOURCE_LIMIT else []
        module = relative_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        result.units = [CodeUnit(unit_id="", repository_id="", commit_sha="", language=self.language, unit_type=UnitType.FILE, name=module,
                                 qualified_name=relative_path, file_path=relative_path, line_start=1, line_end=max(len(lines), 1),
                                 source=text[:FILE_SOURCE_LIMIT], imports=result.imports, exports=result.exports, parser_uncertainty=uncertainty),
                        *walker.units]
        if tree.root_node.has_error:
            result.parse_status = ParseStatus.PARTIAL
            first = next((n for n in _iter(tree.root_node) if n.type == "ERROR" or n.is_missing), None)
            result.parse_error = f"syntax error near line {first.start_point[0] + 1}" if first else "syntax error"
            for unit in result.units: unit.parse_status = ParseStatus.PARTIAL if "syntax errors inside unit" in unit.parser_uncertainty or unit.unit_type == UnitType.FILE else unit.parse_status
        assign_unit_ids(result.units, context)
        return result


class TypeScriptAnalyzer(JavaScriptAnalyzer):
    language = "TypeScript"
    extensions = frozenset({".ts", ".tsx", ".mts", ".cts"})

    def dialect(self, relative_path: str) -> str:
        return "tsx" if relative_path.lower().endswith(".tsx") else "typescript"

    def analyze_file(self, absolute_path: Path, relative_path: str, context: AnalysisContext | None = None) -> FileAnalysis:
        if relative_path.lower().endswith(".d.ts"):   # ambient declarations: types only, no implementations
            return FileAnalysis(path=relative_path, language=self.language, parse_status=ParseStatus.SKIPPED, parse_error="declaration file (.d.ts)")
        return super().analyze_file(absolute_path, relative_path, context)


_TOP_LEVEL = re.compile(r"^(?:export\s+|async\s+|declare\s+|default\s+|abstract\s+)*(?:function\b|class\b|const\b|let\b|var\b|interface\b|type\b|enum\b|namespace\b|module\.exports\b|exports\.)")


def _recover(text: str, walker: "_FileWalker", parser=None) -> list:
    """Error recovery: re-parse each top-level declaration chunk on its own, so one syntax error does not hide
    later valid definitions. Chunks are padded with newlines so tree-sitter rows stay file-relative."""
    lines = text.split("\n")
    starts = [i for i, line in enumerate(lines) if _TOP_LEVEL.match(line)] or [0]
    if starts[0] != 0: starts.insert(0, 0)
    pending = []
    for begin, end in zip(starts, [*starts[1:], len(lines)]):
        chunk = "\n" * begin + "\n".join(lines[begin:end])
        walker.walk((parser or _parser()).parse(chunk.encode("utf-8")).root_node, None, pending)
    return pending


def _iter(node):
    stack = [node]
    while stack:
        current = stack.pop(); yield current
        stack.extend(reversed(current.children))
